"""Meta Ads: connect your own Meta account, read campaigns, pause/resume,
change daily budgets.

Every endpoint works on the *caller's own* connection row (``ScopedQuery.
meta_ad_connections``); there is no parameter that names another user, and the
token never leaves this process. Writes demand ``confirm: true`` in the body
so an API call cannot skip the confirmation the UI shows, and they are written
to the audit log by the middleware with the before/after values attached here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import TypeVar

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.audit import _write_entry
from app.config import settings
from app.db import system_scope
from app.deps import PrincipalDep, ScopedDep, SessionDep, require
from app.errors import ApiError, bad_request, not_found
from app.meta_ads import (
    DATE_PRESETS,
    AdsClient,
    GraphAds,
    MetaApiError,
    MetaAuthError,
    authorize_url,
    exchange_code,
    hash_state,
    new_oauth_state,
    to_major,
    to_minor,
)
from app.meta_crypto import decrypt_token, encrypt_token
from app.models import (
    META_CONNECTED,
    META_DISCONNECTED,
    META_PENDING,
    META_REAUTH_REQUIRED,
    MetaAdConnection,
    User,
)
from app.rbac import has
from app.schemas import (
    MetaAdAccountOut,
    MetaAdAccountSelect,
    MetaAdsStatus,
    MetaBudgetChange,
    MetaCampaignList,
    MetaCampaignOut,
    MetaInsightRow,
    MetaInsights,
    MetaStatusChange,
    MetaWriteResult,
)

router = APIRouter(prefix="/meta-ads", tags=["meta-ads"])

REQUIRED_SCOPES = ("ads_read", "ads_management")
_CAMPAIGN_ID = re.compile(r"^\d{1,32}$")
T = TypeVar("T")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _own_row(scoped: ScopedDep, db: SessionDep) -> MetaAdConnection | None:
    return db.execute(scoped.meta_ad_connections()).scalar_one_or_none()


def _state_of(row: MetaAdConnection | None) -> str:
    if row is None or not row.access_token_enc or row.status in (
        META_DISCONNECTED,
        META_PENDING,
    ):
        return "disconnected"
    if row.status == META_REAUTH_REQUIRED:
        return "reauth_required"
    if row.token_expires_at and row.token_expires_at <= _now():
        return "reauth_required"
    return "connected"


def _require_configured() -> None:
    if not settings.meta_ads_enabled:
        raise ApiError(
            503,
            "meta_not_configured",
            "Meta Ads is not configured on this server. Set META_APP_ID, "
            "META_APP_SECRET, META_REDIRECT_URI and META_TOKEN_ENCRYPTION_KEY.",
        )


def _mark_reauth(db: SessionDep, row: MetaAdConnection, reason: str) -> ApiError:
    row.status = META_REAUTH_REQUIRED
    row.last_error = reason[:500]
    row.updated_at = _now()
    db.commit()
    return ApiError(
        409,
        "meta_reauth_required",
        "Your Meta authorization has expired or was revoked. Reconnect Meta Ads.",
    )


def _live(
    scoped: ScopedDep, db: SessionDep, *, need_account: bool = True
) -> tuple[MetaAdConnection, str]:
    _require_configured()
    row = _own_row(scoped, db)
    state = _state_of(row)
    if state == "disconnected":
        raise ApiError(409, "meta_not_connected", "Connect Meta Ads first.")
    if state == "reauth_required":
        raise _mark_reauth(db, row, row.last_error or "Token expired.")
    token = decrypt_token(row.access_token_enc)
    if token is None:
        raise _mark_reauth(db, row, "Stored token could not be decrypted (key rotated?).")
    if need_account and not row.ad_account_id:
        raise ApiError(409, "meta_no_ad_account", "Choose an ad account first.")
    return row, token


def _call(db: SessionDep, row: MetaAdConnection, fn: Callable[[], T]) -> T:
    try:
        return fn()
    except MetaAuthError as exc:
        raise _mark_reauth(db, row, str(exc)) from exc
    except MetaApiError as exc:
        raise ApiError(502, "meta_upstream_error", f"Meta: {exc}") from exc


def _campaign_out(c: dict, currency: str | None) -> MetaCampaignOut:
    return MetaCampaignOut(
        id=c["id"],
        name=c["name"],
        status=c["status"],
        effective_status=c["effective_status"],
        objective=c.get("objective"),
        daily_budget=to_major(c.get("daily_budget"), currency),
        lifetime_budget=to_major(c.get("lifetime_budget"), currency),
        budget_remaining=to_major(c.get("budget_remaining"), currency),
        start_time=c.get("start_time"),
        stop_time=c.get("stop_time"),
    )


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=MetaAdsStatus,
    dependencies=[Depends(require("meta_ads.read"))],
)
def status(principal: PrincipalDep, scoped: ScopedDep, db: SessionDep) -> MetaAdsStatus:
    row = _own_row(scoped, db)
    state = _state_of(row)
    if row is not None and state == "reauth_required" and row.status != META_REAUTH_REQUIRED:
        row.status = META_REAUTH_REQUIRED
        row.last_error = row.last_error or "Token expired."
        db.commit()
    connected = state != "disconnected"
    granted = set(row.scopes or []) if row else set()
    return MetaAdsStatus(
        configured=settings.meta_ads_enabled,
        state=state,
        meta_user_name=row.meta_user_name if connected else None,
        ad_account_id=row.ad_account_id if connected else None,
        ad_account_name=row.ad_account_name if connected else None,
        currency=row.ad_account_currency if connected else None,
        token_expires_at=row.token_expires_at if connected else None,
        missing_scopes=[s for s in REQUIRED_SCOPES if s not in granted] if connected else [],
        last_error=row.last_error if row else None,
        can_manage=has(principal, "meta_ads.manage"),
    )


@router.post("/oauth/start", dependencies=[Depends(require("meta_ads.manage"))])
def oauth_start(
    principal: PrincipalDep, scoped: ScopedDep, db: SessionDep, request: Request
) -> dict:
    _require_configured()
    state, state_hash, expires = new_oauth_state()
    row = _own_row(scoped, db)
    if row is None:
        row = MetaAdConnection(user_id=principal.id, status=META_PENDING)
        db.add(row)
    row.oauth_state_hash = state_hash
    row.oauth_state_expires_at = expires
    row.updated_at = _now()
    db.commit()
    request.state.audit.action_override = "connect_start"
    request.state.audit.set_resource(row.id)
    return {"authorize_url": authorize_url(state)}


def _back(result: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.meta_redirect_after_connect}?meta={result}", status_code=303
    )


@router.get("/oauth/callback", include_in_schema=False)
def oauth_callback(
    db: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Meta redirects the browser here. There is no CRM session on this
    request (it is a cross-site navigation to the API's domain), so the
    single-use ``state`` is what identifies the user who started the flow."""
    if not settings.meta_ads_enabled or not state:
        return _back("error")

    with system_scope():
        row = db.execute(
            select(MetaAdConnection).where(
                MetaAdConnection.oauth_state_hash == hash_state(state)
            )
        ).scalar_one_or_none()
        user = db.get(User, row.user_id) if row else None
    if row is None:
        return _back("error")

    expired = not row.oauth_state_expires_at or row.oauth_state_expires_at <= _now()
    row.oauth_state_hash = None
    row.oauth_state_expires_at = None
    row.updated_at = _now()
    if expired or user is None or user.deleted_at is not None:
        db.commit()
        return _back("expired")
    if error or not code:
        if row.status == META_PENDING:
            row.status = META_DISCONNECTED
        db.commit()
        return _back("cancelled")

    try:
        token, token_expires = exchange_code(code)
        graph = GraphAds(token)
        me = graph.me()
        scopes = graph.granted_scopes()
        accounts = graph.ad_accounts()
    except (MetaAuthError, MetaApiError) as exc:
        row.last_error = str(exc)[:500]
        if row.status == META_PENDING:
            row.status = META_DISCONNECTED
        db.commit()
        return _back("error")

    chosen = next((a for a in accounts if a["id"] == row.ad_account_id), None) or (
        accounts[0] if accounts else None
    )
    row.access_token_enc = encrypt_token(token)
    row.token_expires_at = token_expires
    row.scopes = scopes
    row.meta_user_id = str(me.get("id") or "")
    row.meta_user_name = me.get("name")
    row.ad_account_id = chosen["id"] if chosen else None
    row.ad_account_name = chosen["name"] if chosen else None
    row.ad_account_currency = chosen["currency"] if chosen else None
    row.status = META_CONNECTED
    row.last_error = None
    row.connected_at = _now()
    db.commit()

    _write_entry(
        user_id=row.user_id,
        action="connect",
        resource_type="meta_ads",
        resource_id=row.id,
        detail={
            "path": "/meta-ads/oauth/callback",
            "meta_user_id": row.meta_user_id,
            "ad_account_id": row.ad_account_id,
            "ad_accounts_available": len(accounts),
            "scopes": scopes,
        },
    )
    return _back("connected")


@router.post("/disconnect", dependencies=[Depends(require("meta_ads.manage"))])
def disconnect(scoped: ScopedDep, db: SessionDep, request: Request) -> dict:
    request.state.audit.action_override = "disconnect"
    row = _own_row(scoped, db)
    if row is None:
        return {"state": "disconnected"}
    token = decrypt_token(row.access_token_enc) if row.access_token_enc else None
    revoked = False
    if token and settings.meta_ads_enabled:
        try:
            GraphAds(token).revoke()
            revoked = True
        except Exception:  # best effort: the local wipe below is what matters
            pass
    row.access_token_enc = None
    row.token_expires_at = None
    row.scopes = None
    row.status = META_DISCONNECTED
    row.oauth_state_hash = None
    row.last_error = None
    row.updated_at = _now()
    db.commit()
    request.state.audit.set_resource(row.id)
    request.state.audit.add(revoked_at_meta=revoked)
    return {"state": "disconnected"}


@router.get(
    "/ad-accounts",
    response_model=list[MetaAdAccountOut],
    dependencies=[Depends(require("meta_ads.read"))],
)
def ad_accounts(scoped: ScopedDep, db: SessionDep) -> list[MetaAdAccountOut]:
    row, token = _live(scoped, db, need_account=False)
    rows = _call(db, row, lambda: GraphAds(token).ad_accounts())
    return [MetaAdAccountOut(**a) for a in rows]


@router.post(
    "/ad-account",
    response_model=MetaAdsStatus,
    dependencies=[Depends(require("meta_ads.manage"))],
)
def select_ad_account(
    payload: MetaAdAccountSelect,
    principal: PrincipalDep,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> MetaAdsStatus:
    row, token = _live(scoped, db, need_account=False)
    accounts = _call(db, row, lambda: GraphAds(token).ad_accounts())
    chosen = next((a for a in accounts if a["id"] == payload.ad_account_id), None)
    if chosen is None:
        raise not_found("Ad account")
    before = row.ad_account_id
    row.ad_account_id = chosen["id"]
    row.ad_account_name = chosen["name"]
    row.ad_account_currency = chosen["currency"]
    row.updated_at = _now()
    db.commit()
    request.state.audit.action_override = "edit"
    request.state.audit.set_resource(row.id)
    request.state.audit.record_changes({"ad_account_id": before}, {"ad_account_id": chosen["id"]})
    return status(principal, scoped, db)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns",
    response_model=MetaCampaignList,
    dependencies=[Depends(require("meta_ads.read"))],
)
def campaigns(scoped: ScopedDep, db: SessionDep) -> MetaCampaignList:
    row, token = _live(scoped, db)
    rows, via = _call(db, row, lambda: AdsClient(token, row.ad_account_id).campaigns())
    currency = row.ad_account_currency
    return MetaCampaignList(
        campaigns=[_campaign_out(c, currency) for c in rows], currency=currency, via=via
    )


@router.get(
    "/insights",
    response_model=MetaInsights,
    dependencies=[Depends(require("meta_ads.read"))],
)
def insights(
    scoped: ScopedDep,
    db: SessionDep,
    date_preset: str = Query("last_7d"),
) -> MetaInsights:
    if date_preset not in DATE_PRESETS:
        raise bad_request("invalid_date_preset", f"date_preset must be one of {', '.join(DATE_PRESETS)}.")
    row, token = _live(scoped, db)
    rows, via = _call(db, row, lambda: AdsClient(token, row.ad_account_id).insights(date_preset))
    spend = sum(r["spend"] for r in rows)
    impressions = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    totals = MetaInsightRow(
        campaign_id="",
        campaign_name="All campaigns",
        spend=round(spend, 2),
        impressions=impressions,
        reach=sum(r["reach"] for r in rows),
        clicks=clicks,
        ctr=round(clicks / impressions * 100, 2) if impressions else 0.0,
        cpc=round(spend / clicks, 2) if clicks else 0.0,
        cpm=round(spend / impressions * 1000, 2) if impressions else 0.0,
        leads=sum(r["leads"] for r in rows),
    )
    return MetaInsights(
        date_preset=date_preset,
        currency=row.ad_account_currency,
        rows=[MetaInsightRow(**r) for r in rows],
        totals=totals,
        via=via,
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _write_preamble(
    campaign_id: str, confirm: bool, scoped: ScopedDep, db: SessionDep, request: Request
) -> tuple[MetaAdConnection, AdsClient, dict]:
    if not _CAMPAIGN_ID.match(campaign_id):
        raise not_found("Campaign")
    request.state.audit.action_override = "edit"
    request.state.audit.add(campaign_id=campaign_id)
    if int(campaign_id) < 2**63:
        request.state.audit.set_resource(int(campaign_id))
    if not confirm:
        raise bad_request(
            "confirmation_required", "Confirm the change before it is sent to Meta."
        )
    row, token = _live(scoped, db)
    client = AdsClient(token, row.ad_account_id)
    request.state.audit.add(ad_account_id=row.ad_account_id)

    def owned() -> dict:
        try:
            c = client.graph.campaign(campaign_id)
        except MetaApiError:
            raise not_found("Campaign") from None
        if c.get("account_id") != row.ad_account_id.removeprefix("act_"):
            raise not_found("Campaign")
        return c

    before = _call(db, row, owned)
    request.state.audit.add(campaign_name=before["name"])
    return row, client, before


@router.post(
    "/campaigns/{campaign_id}/status",
    response_model=MetaWriteResult,
    dependencies=[Depends(require("meta_ads.manage"))],
)
def change_status(
    campaign_id: str,
    payload: MetaStatusChange,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> MetaWriteResult:
    row, client, before = _write_preamble(campaign_id, payload.confirm, scoped, db, request)
    request.state.audit.add(meta_action="resume" if payload.status == "ACTIVE" else "pause")
    via = _call(db, row, lambda: client.set_status(campaign_id, payload.status))
    after = _call(db, row, lambda: client.graph.campaign(campaign_id))
    request.state.audit.add(via=via)
    request.state.audit.record_changes({"status": before["status"]}, {"status": after["status"]})
    return MetaWriteResult(campaign=_campaign_out(after, row.ad_account_currency), via=via)


@router.post(
    "/campaigns/{campaign_id}/budget",
    response_model=MetaWriteResult,
    dependencies=[Depends(require("meta_ads.manage"))],
)
def change_budget(
    campaign_id: str,
    payload: MetaBudgetChange,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> MetaWriteResult:
    row, client, before = _write_preamble(campaign_id, payload.confirm, scoped, db, request)
    currency = row.ad_account_currency
    request.state.audit.add(meta_action="daily_budget", currency=currency)
    if before.get("daily_budget") is None:
        raise bad_request(
            "budget_not_on_campaign",
            "This campaign has no campaign-level daily budget (it uses ad set "
            "budgets or a lifetime budget). Change it in Ads Manager.",
        )
    minor = to_minor(Decimal(payload.daily_budget), currency)
    via = _call(db, row, lambda: client.set_daily_budget(campaign_id, minor))
    after = _call(db, row, lambda: client.graph.campaign(campaign_id))
    request.state.audit.add(via=via)
    request.state.audit.record_changes(
        {"daily_budget": str(to_major(before["daily_budget"], currency))},
        {"daily_budget": str(to_major(after["daily_budget"], currency))},
    )
    return MetaWriteResult(campaign=_campaign_out(after, currency), via=via)
