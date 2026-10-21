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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TypeVar

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.audit import _write_entry
from app.config import settings
from app.db import SCOPE_MARKER, system_scope
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
from app import meta_leads as leads_svc
from app import meta_reels
from app.meta_crypto import decrypt_token, encrypt_token
from app.models import (
    META_CONNECTED,
    META_LEAD_FAILED,
    Contact,
    MetaLead,
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
    MetaCampaignLeadRow,
    MetaLeadFormOut,
    MetaLeadOut,
    MetaLeadPerformance,
    MetaLeadSyncResult,
    MetaPageOut,
    MetaPageSelect,
    MetaReelCampaignCreate,
    MetaReelCampaignResult,
    MetaReelSuggestions,
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
        page_id=row.page_id if connected and row else None,
        page_name=row.page_name if connected and row else None,
        instagram_username=row.instagram_username if connected and row else None,
        leads_live=bool(connected and row and row.page_subscribed_at)
        and bool(settings.meta_webhook_verify_token),
        webhook_configured=bool(settings.meta_webhook_verify_token),
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


def _apply_page(db: SessionDep, row: MetaAdConnection, page: dict) -> None:
    """Record the Page / Instagram account and subscribe the Page to lead
    delivery. Subscription failing is recorded, not raised: the connection and
    campaign tools still work without it."""
    row.page_id = page["id"]
    row.page_name = page["name"]
    row.instagram_id = page.get("instagram_id")
    row.instagram_username = page.get("instagram_username")
    row.page_subscribed_at = None
    try:
        if page.get("access_token"):
            GraphAds(page["access_token"]).subscribe_page_to_leads(page["id"])
            row.page_subscribed_at = _now()
    except (MetaAuthError, MetaApiError) as exc:
        row.last_error = f"Could not subscribe the Page to leads: {exc}"[:500]
    row.updated_at = _now()
    db.commit()


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

    # One Page is the common case; choose it so leads work without a second
    # step. Several Pages means the owner picks on the Meta Ads screen.
    try:
        pages = graph.pages()
        keep = next((p for p in pages if p["id"] == row.page_id), None)
        if keep or len(pages) == 1:
            _apply_page(db, row, keep or pages[0])
    except (MetaAuthError, MetaApiError) as exc:
        row.last_error = f"Page setup: {exc}"[:500]
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


# ---------------------------------------------------------------------------
# Page, lead forms and Meta Lead Ads intake
# ---------------------------------------------------------------------------


@router.get(
    "/pages",
    response_model=list[MetaPageOut],
    dependencies=[Depends(require("meta_ads.read"))],
)
def pages(scoped: ScopedDep, db: SessionDep) -> list[MetaPageOut]:
    row, token = _live(scoped, db, need_account=False)
    found = _call(db, row, lambda: GraphAds(token).pages())
    return [MetaPageOut(**{k: v for k, v in p.items() if k != "access_token"}) for p in found]


@router.post(
    "/page",
    response_model=MetaAdsStatus,
    dependencies=[Depends(require("meta_ads.manage"))],
)
def select_page(
    payload: MetaPageSelect,
    principal: PrincipalDep,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> MetaAdsStatus:
    row, token = _live(scoped, db, need_account=False)
    found = _call(db, row, lambda: GraphAds(token).pages())
    chosen = next((p for p in found if p["id"] == payload.page_id), None)
    if chosen is None:
        raise not_found("Page")
    before = row.page_id
    _apply_page(db, row, chosen)
    request.state.audit.action_override = "edit"
    request.state.audit.set_resource(row.id)
    request.state.audit.record_changes({"page_id": before}, {"page_id": chosen["id"]})
    return status(principal, scoped, db)


def _page_graph(scoped: ScopedDep, db: SessionDep) -> tuple[MetaAdConnection, str, GraphAds]:
    row, token = _live(scoped, db, need_account=False)
    if not row.page_id:
        raise ApiError(409, "meta_no_page", "Choose a Facebook Page first.")
    graph = _call(db, row, lambda: leads_svc._page_graph(GraphAds(token), row.page_id))
    return row, token, graph


@router.get(
    "/lead-forms",
    response_model=list[MetaLeadFormOut],
    dependencies=[Depends(require("meta_ads.read"))],
)
def lead_forms(scoped: ScopedDep, db: SessionDep) -> list[MetaLeadFormOut]:
    row, _, graph = _page_graph(scoped, db)
    forms = _call(db, row, lambda: graph.lead_forms(row.page_id))
    return [MetaLeadFormOut(**f) for f in forms]


@router.post(
    "/leads/sync",
    response_model=MetaLeadSyncResult,
    dependencies=[Depends(require("meta_ads.manage"))],
)
def sync_leads(scoped: ScopedDep, db: SessionDep, request: Request) -> MetaLeadSyncResult:
    """Read every lead form directly and import what the webhook missed.
    Safe to press repeatedly: a lead already imported is skipped."""
    row, token, _ = _page_graph(scoped, db)
    request.state.audit.action_override = "edit"
    request.state.audit.set_resource(row.id)
    result = _call(db, row, lambda: leads_svc.sync_forms(db, row, token))
    request.state.audit.add(**result)
    return MetaLeadSyncResult(**result)


@router.get(
    "/leads/recent",
    response_model=list[MetaLeadOut],
    dependencies=[Depends(require("meta_ads.read"))],
)
def recent_leads(scoped: ScopedDep, db: SessionDep, limit: int = Query(20, ge=1, le=100)) -> list[MetaLeadOut]:
    rows = db.execute(
        scoped.meta_leads().order_by(MetaLead.created_at.desc()).limit(limit)
    ).scalars().all()
    return [
        MetaLeadOut(
            id=r.id,
            campaign_name=r.campaign_name,
            ad_name=r.ad_name,
            status=r.status,
            contact_id=r.contact_id,
            error=r.error,
            received_at=r.created_at,
        )
        for r in rows
    ]


_PRESET_DAYS = {"today": 0, "yesterday": 1, "last_7d": 7, "last_14d": 14, "last_30d": 30}


def _window_start(preset: str) -> datetime | None:
    now = _now()
    if preset == "maximum":
        return None
    if preset == "this_month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if preset == "last_month":
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (first.replace(day=1) - timedelta(days=1)).replace(day=1)
    days = _PRESET_DAYS[preset]
    return (now - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _per(spend: float, n: int) -> float | None:
    return round(spend / n, 2) if n else None


@router.get(
    "/lead-performance",
    response_model=MetaLeadPerformance,
    dependencies=[Depends(require("meta_ads.read"))],
)
def lead_performance(
    scoped: ScopedDep, db: SessionDep, date_preset: str = Query("last_30d")
) -> MetaLeadPerformance:
    """Ad spend against what the leads actually did in the CRM -- the number
    Ads Manager cannot give: cost per lead *that got a site visit*."""
    if date_preset not in DATE_PRESETS:
        raise bad_request("invalid_date_preset", f"date_preset must be one of {', '.join(DATE_PRESETS)}.")
    row, token = _live(scoped, db)
    ins, _via = _call(db, row, lambda: AdsClient(token, row.ad_account_id).insights(date_preset))
    spend_by = {r["campaign_id"]: r for r in ins}

    start = _window_start(date_preset)
    # Owner-only route (meta_ads.read); the join to contacts is why this is
    # built by hand instead of from scoped.meta_leads().
    q = (
        select(MetaLead.campaign_id, MetaLead.campaign_name, Contact.stage, MetaLead.status)
        .select_from(MetaLead)
        .outerjoin(Contact, (Contact.id == MetaLead.contact_id) & Contact.deleted_at.is_(None))
        .execution_options(**{SCOPE_MARKER: True})
    )
    if start is not None:
        q = q.where(MetaLead.created_at >= start)
    crm: dict[str, dict] = {}
    for campaign_id, name, stage, lead_status in db.execute(q):
        if not campaign_id or lead_status == META_LEAD_FAILED:
            continue
        c = crm.setdefault(campaign_id, {"name": name, "n": 0, "contacted": 0, "qualified": 0, "visited": 0, "closed": 0})
        c["n"] += 1
        c["contacted"] += stage not in (None, "new")
        c["qualified"] += stage in ("site_visit_scheduled", "visited", "negotiating", "closed")
        c["visited"] += stage in ("visited", "negotiating", "closed")
        c["closed"] += stage == "closed"

    def make(cid: str, name: str, spend: float, meta_leads: int, c: dict) -> MetaCampaignLeadRow:
        return MetaCampaignLeadRow(
            campaign_id=cid,
            campaign_name=name,
            spend=round(spend, 2),
            meta_leads=meta_leads,
            crm_leads=c["n"],
            contacted=c["contacted"],
            qualified=c["qualified"],
            visited=c["visited"],
            closed=c["closed"],
            cost_per_lead=_per(spend, c["n"] or meta_leads),
            cost_per_qualified=_per(spend, c["qualified"]),
            cost_per_visit=_per(spend, c["visited"]),
        )

    empty = {"n": 0, "contacted": 0, "qualified": 0, "visited": 0, "closed": 0}
    rows = [
        make(
            cid,
            (spend_by.get(cid) or {}).get("campaign_name") or crm.get(cid, {}).get("name") or cid,
            (spend_by.get(cid) or {}).get("spend", 0.0),
            (spend_by.get(cid) or {}).get("leads", 0),
            crm.get(cid, empty),
        )
        for cid in sorted(set(spend_by) | set(crm))
    ]
    rows.sort(key=lambda r: -r.spend)
    total = {k: sum(getattr(r, k) for r in rows) for k in ("crm_leads", "contacted", "qualified", "visited", "closed")}
    totals = make(
        "",
        "All campaigns",
        sum(r.spend for r in rows),
        sum(r.meta_leads for r in rows),
        {"n": total["crm_leads"], **{k: total[k] for k in ("contacted", "qualified", "visited", "closed")}},
    )
    failed = db.execute(
        select(func.count()).select_from(MetaLead).where(MetaLead.status == META_LEAD_FAILED)
        .execution_options(**{SCOPE_MARKER: True})
    ).scalar_one()
    return MetaLeadPerformance(
        date_preset=date_preset, currency=row.ad_account_currency, rows=rows, totals=totals, failed_leads=failed
    )


# ---------------------------------------------------------------------------
# Instagram reels -> campaign suggestions
# ---------------------------------------------------------------------------


@router.get(
    "/reels/suggestions",
    response_model=MetaReelSuggestions,
    dependencies=[Depends(require("meta_ads.read"))],
)
def reel_suggestions(scoped: ScopedDep, db: SessionDep) -> MetaReelSuggestions:
    row, token = _live(scoped, db, need_account=False)
    if not row.instagram_id:
        raise ApiError(
            409,
            "meta_no_instagram",
            "No Instagram business account is linked to the chosen Facebook Page. "
            "Link one in Meta Business Settings, then reconnect.",
        )
    graph = GraphAds(token)
    reels = _call(db, row, lambda: meta_reels.fetch_reels(graph, row.instagram_id))
    demand = meta_reels.area_demand(db)
    return MetaReelSuggestions(
        instagram_username=row.instagram_username,
        currency=row.ad_account_currency,
        reels=meta_reels.build_suggestions(reels, demand, row.ad_account_currency),
    )


@router.post(
    "/reels/{media_id}/campaign",
    response_model=MetaReelCampaignResult,
    dependencies=[Depends(require("meta_ads.manage"))],
)
def create_reel_campaign(
    media_id: str,
    payload: MetaReelCampaignCreate,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> MetaReelCampaignResult:
    """Create a campaign from a reel -- always PAUSED. Turning it on is a
    separate, confirmed action from the campaign list."""
    if not _CAMPAIGN_ID.match(media_id):
        raise not_found("Reel")
    request.state.audit.action_override = "create"
    request.state.audit.add(media_id=media_id, form_id=payload.form_id)
    if not payload.confirm:
        raise bad_request("confirmation_required", "Confirm before anything is created on Meta.")
    if payload.age_min > payload.age_max:
        raise bad_request("invalid_age_range", "Minimum age cannot exceed maximum age.")
    row, token = _live(scoped, db)
    if not row.page_id or not row.instagram_id:
        raise ApiError(409, "meta_no_instagram", "Choose a Page with a linked Instagram account first.")
    request.state.audit.add(ad_account_id=row.ad_account_id)

    user_graph = GraphAds(token)

    def check() -> None:
        reels = user_graph.ig_media(row.instagram_id, limit=50)
        if not any(m.get("id") == media_id for m in reels):
            raise not_found("Reel")
        pg = leads_svc._page_graph(user_graph, row.page_id)
        if not any(f["id"] == payload.form_id for f in pg.lead_forms(row.page_id)):
            raise bad_request("unknown_form", "That lead form does not belong to the connected Page.")

    _call(db, row, check)

    cities = payload.cities or [c.strip() for c in settings.meta_target_cities.split(",") if c.strip()]
    created = _call(
        db,
        row,
        lambda: meta_reels.create_paused_campaign(
            user_graph,
            account_id=row.ad_account_id,
            currency=row.ad_account_currency,
            page_id=row.page_id,
            instagram_id=row.instagram_id,
            media_id=media_id,
            form_id=payload.form_id,
            name=payload.name,
            daily_budget=payload.daily_budget,
            cities=cities,
            age_min=payload.age_min,
            age_max=payload.age_max,
        ),
    )
    request.state.audit.add(
        daily_budget=str(payload.daily_budget), currency=row.ad_account_currency, **created
    )
    account = row.ad_account_id.removeprefix("act_")
    return MetaReelCampaignResult(
        campaign_id=created["campaign_id"],
        adset_id=created["adset_id"],
        ad_id=created["ad_id"],
        ads_manager_url=(
            f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={account}"
            f"&selected_campaign_ids={created['campaign_id']}"
        ),
    )
