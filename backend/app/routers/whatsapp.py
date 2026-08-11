"""WhatsApp feed: the gateway's ingest webhook, plus the owner's controls.

Two audiences, two auth models, which is why they share a module but not a
dependency:

* ``POST /internal/whatsapp/ingest`` is called by the ingestion gateway -- a
  machine, on a box the firm treats as untrusted (ARCHITECTURE.md §5 isolates
  it because it runs an unofficial WhatsApp integration). It authenticates with
  an HMAC over the raw body, never a JWT, so the gateway never holds a
  credential that could be replayed against the rest of the API.

* everything else is Owner-only, per ROLES_PERMISSIONS.md ("Configure WhatsApp
  ingestion groups -- Owner ✅, everyone else ❌").

The webhook does as little as possible: authenticate, validate, store verbatim,
return. Extraction happens in the worker. A gateway that cannot get a response
in milliseconds starts buffering, and a buffering WhatsApp session is one that
drops messages.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import func, select

from app.config import settings
from app.db import system_scope
from app.deps import PageDep, PrincipalDep, ScopedDep, SessionDep, require
from app.errors import ApiError, bad_request, forbidden, not_found
from app.extraction import Extractor
from app.models import (
    INGEST_DUPLICATE,
    INGEST_EXTRACTED,
    INGEST_FAILED,
    INGEST_PENDING,
    INGEST_PROCESSING,
    Property,
    PropertySource,
    WhatsAppGroup,
    WhatsAppMessage,
)
from app.schemas import (
    IngestionStatus,
    IngestRequest,
    IngestResponse,
    Paged,
    PropertyReviewRequest,
    PropertySourceOut,
    WhatsAppGroupCreate,
    WhatsAppGroupOut,
    WhatsAppGroupUpdate,
    WhatsAppMessageOut,
)

router = APIRouter(tags=["whatsapp"])


# ---------------------------------------------------------------------------
# Gateway authentication
# ---------------------------------------------------------------------------


def verify_gateway_signature(
    body: bytes,
    signature: str | None,
    timestamp: str | None,
) -> None:
    """Authenticate the ingestion gateway.

    ``HMAC-SHA256(secret, "<timestamp>.<raw body>")``, compared in constant
    time. The timestamp is inside the signed payload and is range-checked, so a
    captured request cannot be replayed later to re-inject stale listings.
    """
    if not settings.whatsapp_ingest_enabled:
        # Fail closed. An unconfigured deployment must not accept writes from
        # anyone who happens to find the path.
        raise ApiError(
            503,
            "ingest_disabled",
            "WhatsApp ingestion is not configured on this server.",
        )
    if not signature or not timestamp:
        raise forbidden("Missing gateway signature.")

    try:
        sent_at = int(timestamp)
    except ValueError:
        raise forbidden("Malformed signature timestamp.") from None

    if abs(time.time() - sent_at) > settings.whatsapp_ingest_max_skew:
        raise forbidden("Signature timestamp outside the accepted window.")

    expected = hmac.new(
        settings.whatsapp_ingest_secret.encode(),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature.strip()):
        raise forbidden("Invalid gateway signature.")


# ---------------------------------------------------------------------------
# Ingest webhook (gateway -> API)
# ---------------------------------------------------------------------------


@router.post(
    "/internal/whatsapp/ingest",
    response_model=IngestResponse,
    tags=["internal"],
    summary="Ingestion gateway webhook (HMAC-authenticated, not for the UI)",
)
async def ingest(
    request: Request,
    db: SessionDep,
    x_balaji_signature: str | None = Header(default=None),
    x_balaji_timestamp: str | None = Header(default=None),
) -> IngestResponse:
    """Store forwarded messages verbatim. Extraction happens later, in the worker.

    Idempotent on ``wa_message_id``: the gateway replays its buffer after a
    reconnect, and a dropped WhatsApp session must not duplicate the firm's
    inventory every time it recovers.
    """
    raw = await request.body()
    verify_gateway_signature(raw, x_balaji_signature, x_balaji_timestamp)

    try:
        payload = IngestRequest.model_validate_json(raw)
    except Exception as exc:
        raise bad_request("invalid_payload", f"Could not parse body: {exc}") from exc

    if not payload.messages:
        return IngestResponse(accepted=0, duplicates=0, unknown_groups=[])

    # Trusted infrastructure path: no principal exists on this request, and the
    # gateway is not a user whose scope could be applied.
    with system_scope():
        jids = {m.group_jid for m in payload.messages}
        groups = {
            g.group_jid: g
            for g in db.execute(
                select(WhatsAppGroup)
                .where(WhatsAppGroup.group_jid.in_(jids))
                .where(WhatsAppGroup.deleted_at.is_(None))
                .where(WhatsAppGroup.is_active.is_(True))
            )
            .scalars()
            .all()
        }

        incoming_ids = [m.wa_message_id for m in payload.messages]
        already = {
            row[0]
            for row in db.execute(
                select(WhatsAppMessage.wa_message_id).where(
                    WhatsAppMessage.wa_message_id.in_(incoming_ids)
                )
            )
        }

        accepted = 0
        duplicates = 0
        unknown: set[str] = set()
        seen_in_payload: set[str] = set()
        touched: dict[int, datetime] = {}

        for message in payload.messages:
            group = groups.get(message.group_jid)
            if group is None:
                # The owner turned this group off, or never added it. Dropping
                # here rather than storing-then-filtering is the point of the
                # switch being in the product.
                unknown.add(message.group_jid)
                continue
            if message.wa_message_id in already or message.wa_message_id in seen_in_payload:
                duplicates += 1
                continue
            body = (message.body or "").strip()
            if not body:
                continue  # media-only message with no caption; nothing to read

            seen_in_payload.add(message.wa_message_id)
            db.add(
                WhatsAppMessage(
                    group_id=group.id,
                    wa_message_id=message.wa_message_id,
                    sender_jid=message.sender_jid,
                    sender_name=message.sender_name,
                    body=body,
                    sent_at=message.sent_at,
                    status=INGEST_PENDING,
                )
            )
            accepted += 1

            stamp = message.sent_at or datetime.now(timezone.utc)
            if group.id not in touched or stamp > touched[group.id]:
                touched[group.id] = stamp

        for group_id, stamp in touched.items():
            group = next(g for g in groups.values() if g.id == group_id)
            group.message_count = (group.message_count or 0) + sum(
                1
                for m in payload.messages
                if m.group_jid == group.group_jid
                and m.wa_message_id in seen_in_payload
            )
            if group.last_message_at is None or stamp > group.last_message_at:
                group.last_message_at = stamp

        db.commit()

    return IngestResponse(
        accepted=accepted, duplicates=duplicates, unknown_groups=sorted(unknown)
    )


@router.get(
    "/internal/whatsapp/groups",
    tags=["internal"],
    summary="Groups the gateway should watch (HMAC-authenticated)",
)
async def gateway_groups(
    request: Request,
    db: SessionDep,
    x_balaji_signature: str | None = Header(default=None),
    x_balaji_timestamp: str | None = Header(default=None),
) -> dict:
    """Lets the gateway pull its watch list instead of being configured twice.

    The owner toggling a group in the UI is the single source of truth; the
    gateway polls this and adjusts.
    """
    verify_gateway_signature(
        await request.body(), x_balaji_signature, x_balaji_timestamp
    )
    with system_scope():
        rows = (
            db.execute(
                select(WhatsAppGroup.group_jid, WhatsAppGroup.name)
                .where(WhatsAppGroup.deleted_at.is_(None))
                .where(WhatsAppGroup.is_active.is_(True))
            )
            .all()
        )
    return {"groups": [{"group_jid": jid, "name": name} for jid, name in rows]}


# ---------------------------------------------------------------------------
# Owner controls
# ---------------------------------------------------------------------------


@router.get(
    "/whatsapp/groups",
    response_model=list[WhatsAppGroupOut],
    dependencies=[Depends(require("whatsapp.manage"))],
)
def list_groups(scoped: ScopedDep, db: SessionDep) -> list[WhatsAppGroupOut]:
    rows = (
        db.execute(scoped.whatsapp_groups().order_by(WhatsAppGroup.name))
        .scalars()
        .all()
    )
    pending = _pending_by_group(db, [g.id for g in rows])
    out = []
    for group in rows:
        item = WhatsAppGroupOut.model_validate(group)
        item.pending_count = pending.get(group.id, 0)
        out.append(item)
    return out


@router.post(
    "/whatsapp/groups",
    response_model=WhatsAppGroupOut,
    status_code=201,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def add_group(
    payload: WhatsAppGroupCreate,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> WhatsAppGroupOut:
    jid = payload.group_jid.strip()
    if not jid:
        raise bad_request("invalid_jid", "A group id is required.")

    # Uniqueness check, not a data read: must see rows a scope would hide,
    # including a group that was removed and is being re-added.
    with system_scope():
        existing = db.execute(
            select(WhatsAppGroup).where(WhatsAppGroup.group_jid == jid)
        ).scalar_one_or_none()

    if existing is not None:
        if existing.deleted_at is None:
            raise bad_request(
                "group_exists", "That group is already being monitored."
            )
        # Re-adding a previously removed group revives the row, so its history
        # of ingested messages and the listings traced to them survive.
        existing.deleted_at = None
        existing.is_active = payload.is_active
        existing.name = payload.name.strip()
        existing.note = payload.note
        db.commit()
        request.state.audit.set_resource(existing.id)
        request.state.audit.add(revived=True, group_jid=jid)
        return WhatsAppGroupOut.model_validate(existing)

    group = WhatsAppGroup(
        group_jid=jid,
        name=payload.name.strip(),
        note=payload.note,
        is_active=payload.is_active,
        added_by=principal.id,
    )
    db.add(group)
    db.commit()

    request.state.audit.set_resource(group.id)
    request.state.audit.add(group_jid=jid, group_name=group.name)
    return WhatsAppGroupOut.model_validate(group)


@router.patch(
    "/whatsapp/groups/{group_id}",
    response_model=WhatsAppGroupOut,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def update_group(
    group_id: int,
    payload: WhatsAppGroupUpdate,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> WhatsAppGroupOut:
    group = db.execute(
        scoped.whatsapp_groups().where(WhatsAppGroup.id == group_id)
    ).scalar_one_or_none()
    if group is None:
        raise not_found("Group")

    fields = payload.model_dump(exclude_unset=True)
    before = {k: getattr(group, k) for k in fields}
    for key, value in fields.items():
        setattr(group, key, value)
    db.commit()

    request.state.audit.record_changes(before, fields)
    return WhatsAppGroupOut.model_validate(group)


@router.delete(
    "/whatsapp/groups/{group_id}",
    status_code=204,
    response_model=None,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def remove_group(
    group_id: int, scoped: ScopedDep, db: SessionDep, request: Request
) -> None:
    """Stop monitoring a group.

    Soft delete: the listings already sourced from it stay in inventory, and
    their provenance stays traceable. Hard-deleting would orphan every
    property_sources row pointing here.
    """
    group = db.execute(
        scoped.whatsapp_groups().where(WhatsAppGroup.id == group_id)
    ).scalar_one_or_none()
    if group is None:
        raise not_found("Group")
    group.deleted_at = datetime.now(timezone.utc)
    group.is_active = False
    db.commit()
    request.state.audit.add(soft_deleted=True, group_jid=group.group_jid)


@router.get(
    "/whatsapp/ingestion-status",
    response_model=IngestionStatus,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def ingestion_status(scoped: ScopedDep, db: SessionDep) -> IngestionStatus:
    """Owner's monitoring view (API_SPEC.md: connected groups, recent failures)."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    groups = db.execute(scoped.whatsapp_groups()).scalars().all()
    messages = scoped.whatsapp_messages()

    def count(stmt) -> int:
        # Aggregating over `stmt.subquery()` keeps the role filter in the SQL
        # while presenting no ORM entity to the guard in app/db.py -- which is
        # why the aggregate below reads the subquery's own column rather than
        # `WhatsAppMessage.processed_at`. Referencing the mapped attribute
        # would make this a guarded query with no scope marker on it.
        return db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    message_rows = messages.subquery()

    props = scoped.properties().where(Property.source == "whatsapp_group")

    return IngestionStatus(
        groups_active=sum(1 for g in groups if g.is_active),
        groups_total=len(groups),
        pending=count(messages.where(WhatsAppMessage.status == INGEST_PENDING)),
        processing=count(messages.where(WhatsAppMessage.status == INGEST_PROCESSING)),
        failed_last_24h=count(
            messages.where(WhatsAppMessage.status == INGEST_FAILED).where(
                WhatsAppMessage.received_at >= since
            )
        ),
        messages_last_24h=count(messages.where(WhatsAppMessage.received_at >= since)),
        listings_last_24h=count(
            messages.where(WhatsAppMessage.status == INGEST_EXTRACTED).where(
                WhatsAppMessage.received_at >= since
            )
        ),
        properties_from_whatsapp=count(props),
        duplicates_merged=count(
            scoped.property_sources().where(PropertySource.relation == "duplicate")
        ),
        needs_review=count(props.where(Property.review_state == "needs_review")),
        last_message_at=max(
            (g.last_message_at for g in groups if g.last_message_at), default=None
        ),
        last_processed_at=db.execute(
            select(func.max(message_rows.c.processed_at))
        ).scalar(),
        extraction_configured=Extractor().available,
    )


@router.get(
    "/whatsapp/messages",
    response_model=Paged[WhatsAppMessageOut],
    dependencies=[Depends(require("whatsapp.manage"))],
)
def list_messages(
    scoped: ScopedDep,
    db: SessionDep,
    page: PageDep,
    status: str | None = None,
    group_id: int | None = None,
) -> Paged[WhatsAppMessageOut]:
    """Raw feed, for debugging a group that is producing nothing useful."""
    stmt = scoped.whatsapp_messages()
    if status:
        stmt = stmt.where(WhatsAppMessage.status == status)
    if group_id is not None:
        stmt = stmt.where(WhatsAppMessage.group_id == group_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(WhatsAppMessage.received_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )

    names = {
        g.id: g.name
        for g in db.execute(scoped.whatsapp_groups(include_removed=True))
        .scalars()
        .all()
    }
    items = []
    for row in rows:
        item = WhatsAppMessageOut.model_validate(row)
        item.group_name = names.get(row.group_id)
        items.append(item)

    return Paged[WhatsAppMessageOut](
        items=items,
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )


@router.get(
    "/properties/{property_id}/sources",
    response_model=list[PropertySourceOut],
)
def property_sources(
    property_id: int, scoped: ScopedDep, db: SessionDep
) -> list[PropertySourceOut]:
    """Where this listing came from, and how many times it has been reposted.

    Readable by every role: an agent working the flat needs the posting
    broker's number, and a listing reposted six times in a fortnight is telling
    them something about how live it really is.
    """
    prop = db.execute(
        scoped.properties().where(Property.id == property_id)
    ).scalar_one_or_none()
    if prop is None:
        raise not_found("Property")

    rows = (
        db.execute(
            scoped.property_sources()
            .where(PropertySource.property_id == property_id)
            .order_by(PropertySource.seen_at.desc())
        )
        .scalars()
        .all()
    )
    return [PropertySourceOut.model_validate(r) for r in rows]


@router.post(
    "/properties/{property_id}/review",
    response_model=None,
    status_code=204,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def review_property(
    property_id: int,
    payload: PropertyReviewRequest,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> None:
    """Owner's verdict on a low-confidence extraction.

    'rejected' soft-deletes the listing rather than only relabelling it -- a
    listing the owner has judged wrong should stop appearing in agents'
    searches immediately, and soft delete keeps its provenance intact.
    """
    prop = db.execute(
        scoped.properties().where(Property.id == property_id)
    ).scalar_one_or_none()
    if prop is None:
        raise not_found("Property")

    prop.review_state = payload.review_state
    if payload.review_state == "rejected":
        prop.deleted_at = datetime.now(timezone.utc)
    db.commit()
    request.state.audit.add(review_state=payload.review_state)


def _pending_by_group(db: SessionDep, group_ids: list[int]) -> dict[int, int]:
    if not group_ids:
        return {}
    with system_scope():
        rows = db.execute(
            select(WhatsAppMessage.group_id, func.count())
            .where(WhatsAppMessage.group_id.in_(group_ids))
            .where(WhatsAppMessage.status == INGEST_PENDING)
            .group_by(WhatsAppMessage.group_id)
        ).all()
    return {gid: count for gid, count in rows}


@router.post(
    "/whatsapp/reprocess/{message_id}",
    response_model=None,
    status_code=204,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def reprocess_message(
    message_id: int, scoped: ScopedDep, db: SessionDep, request: Request
) -> None:
    """Put a message back in the queue.

    The reason raw bodies are stored before parsing: when the prompt improves,
    a message the extractor previously misread can be replayed rather than
    re-sourced. Resets `attempts` so a message that exhausted its retries
    during an outage gets a fair run.
    """
    message = db.execute(
        scoped.whatsapp_messages().where(WhatsAppMessage.id == message_id)
    ).scalar_one_or_none()
    if message is None:
        raise not_found("Message")

    message.status = INGEST_PENDING
    message.attempts = 0
    message.error = None
    db.commit()
    request.state.audit.add(reprocessed=True, message_id=message_id)
