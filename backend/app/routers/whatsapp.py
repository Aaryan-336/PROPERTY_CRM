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
from app.heartbeat import is_live
from app.models import (
    EXTRACTION_WORKER,
    INGEST_DUPLICATE,
    INGEST_EXTRACTED,
    INGEST_FAILED,
    INGEST_PENDING,
    INGEST_PROCESSING,
    Property,
    PropertySource,
    WhatsAppGroup,
    WhatsAppGroupCandidate,
    WhatsAppMessage,
    WhatsAppSession,
    WorkerHeartbeat,
)
from app.schemas import (
    DirectoryReport,
    GatewayCommands,
    GroupCandidateOut,
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
    SessionOut,
    SessionReport,
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

    # Not scoped, and deliberately not scopable: a heartbeat belongs to a
    # process, not to a person, so there is no role filter that would mean
    # anything here. `worker_heartbeats` is left out of GUARDED_MAPPERS for the
    # same reason, which is why this is a plain get rather than system_scope().
    beat = db.get(WorkerHeartbeat, EXTRACTION_WORKER)

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
        extractor_running=is_live(beat.seen_at if beat else None),
        extractor_seen_at=beat.seen_at if beat else None,
        extractor_note=beat.note if beat else None,
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
    dependencies=[Depends(require("properties.read"))],
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


# ---------------------------------------------------------------------------
# Pairing (gateway <-> API <-> owner's browser)
# ---------------------------------------------------------------------------

# How long after the gateway's last report we stop believing its state. It
# reports on every socket event and heartbeats between them, so silence this
# long means the process is gone, not idle.
SESSION_STALE_AFTER = timedelta(seconds=90)


@router.post(
    "/internal/whatsapp/session",
    tags=["internal"],
    summary="Gateway reports its connection state (HMAC-authenticated)",
)
async def report_session(request: Request, db: SessionDep) -> dict:
    """The gateway pushing its socket state, including the pairing QR.

    Same HMAC as the ingest webhook, and for the same reason: the gateway has
    no user identity, and this endpoint is what puts a scannable QR on the
    owner's screen — anyone who could write here could show the owner a QR that
    links *their* account instead.
    """
    body = await request.body()
    verify_gateway_signature(
        body,
        request.headers.get("x-balaji-signature"),
        request.headers.get("x-balaji-timestamp"),
    )
    payload = SessionReport.model_validate_json(body)

    now = datetime.now(timezone.utc)
    with system_scope():
        session = db.get(WhatsAppSession, 1)
        if session is None:
            session = WhatsAppSession(id=1)
            db.add(session)

        session.state = payload.state
        # Only a `qr` report carries one. Clearing it on every other state is
        # what stops a scanned-and-spent QR lingering on the screen.
        session.qr = payload.qr if payload.state == "qr" else None
        session.qr_expires_at = (
            now + timedelta(seconds=payload.qr_ttl_seconds or 20)
            if payload.state == "qr"
            else None
        )
        if payload.jid:
            session.jid = payload.jid
        if payload.display_name:
            session.display_name = payload.display_name
        session.last_error = payload.last_error
        session.updated_at = now
        db.commit()

    return {"ok": True}


@router.get(
    "/whatsapp/session",
    response_model=SessionOut,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def get_session(db: SessionDep, request: Request) -> SessionOut:
    """Connection state for the owner's pairing screen.

    Polled every couple of seconds while a QR is on screen, so it is
    deliberately cheap: one row plus a count.

    Owner-only under the same capability as group management. The QR here is a
    live credential — scanning it links a WhatsApp account to this deployment —
    so it must never be readable by staff.
    """
    now = datetime.now(timezone.utc)
    with system_scope():
        session = db.get(WhatsAppSession, 1)
        watched = db.execute(
            select(func.count())
            .select_from(WhatsAppGroup)
            .where(WhatsAppGroup.is_active.is_(True))
            .where(WhatsAppGroup.deleted_at.is_(None))
        ).scalar_one()
        known = db.execute(
            select(func.count()).select_from(WhatsAppGroupCandidate)
        ).scalar_one()

    if session is None:
        return SessionOut(
            state="disconnected",
            updated_at=now,
            stale=True,
            watched_groups=watched,
            directory_count=known,
        )

    stale = (now - session.updated_at) > SESSION_STALE_AFTER
    expired = session.qr_expires_at is not None and session.qr_expires_at <= now

    request.state.audit.add(state=session.state, stale=stale)

    return SessionOut(
        state=session.state,
        # Never hand back a QR that has already rotated. It would render
        # perfectly and fail on the phone with no explanation.
        qr=None if (expired or stale) else session.qr,
        qr_expires_at=session.qr_expires_at,
        jid=session.jid,
        display_name=session.display_name,
        last_error=session.last_error,
        updated_at=session.updated_at,
        stale=stale,
        watched_groups=watched,
        pair_pending=session.pair_requested_at is not None,
        pair_requested_at=session.pair_requested_at,
        directory_count=known,
        directory_synced_at=session.directory_synced_at,
    )


# ---------------------------------------------------------------------------
# Pairing, driven from the browser
# ---------------------------------------------------------------------------


def _session_row(db: SessionDep) -> WhatsAppSession:
    """The one session row, created if a fresh database has not seeded it.

    Caller must already hold ``system_scope``.
    """
    session = db.get(WhatsAppSession, 1)
    if session is None:
        session = WhatsAppSession(id=1)
        db.add(session)
    return session


@router.post(
    "/whatsapp/pair",
    response_model=SessionOut,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def request_pairing(db: SessionDep, request: Request) -> SessionOut:
    """Ask the gateway to start a fresh pairing, so a QR appears.

    This is the press behind the button. A QR is not something the API can
    produce -- only the gateway's WhatsApp socket emits one, and only while it
    is asking to be linked. Before this existed, a gateway holding a saved
    session emitted nothing, so the pairing screen sat empty and the only way
    to get a code was to delete the session directory by hand on the server.

    Recorded rather than executed: the gateway polls, claims the request and
    acts. It is also the gateway that enforces the cooldown between re-pairings,
    because relinking an account over and over is exactly the pattern that gets
    a number flagged.
    """
    now = datetime.now(timezone.utc)
    with system_scope():
        session = _session_row(db)
        session.pair_requested_at = now
        # A failure from the last attempt would otherwise sit under the new QR
        # as if it had just happened.
        session.last_error = None
        db.commit()

    request.state.audit.add(pair_requested=True)
    return get_session(db, request)


@router.delete(
    "/whatsapp/pair",
    response_model=SessionOut,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def cancel_pairing(db: SessionDep, request: Request) -> SessionOut:
    """Withdraw a pairing request that has not been claimed yet.

    A queued command outlives the screen that queued it. Without this, an owner
    who pressed Connect while the gateway was down had no way to take it back:
    the request sat in the database, and whenever the gateway next started --
    minutes or days later, on somebody else's watch -- it would claim the
    command and wipe a perfectly good WhatsApp session to show a QR nobody was
    waiting for any more.

    Only clears the request. A pairing the gateway has already claimed is gone
    from here and is being acted on; this cannot reach into that.
    """
    with system_scope():
        session = _session_row(db)
        was_pending = session.pair_requested_at is not None
        session.pair_requested_at = None
        db.commit()

    request.state.audit.add(pair_cancelled=True, was_pending=was_pending)
    return get_session(db, request)


@router.post(
    "/whatsapp/sync-groups",
    response_model=SessionOut,
    dependencies=[Depends(require("whatsapp.manage"))],
)
def request_group_sync(db: SessionDep, request: Request) -> SessionOut:
    """Ask the gateway to re-read the group list off WhatsApp.

    The gateway uploads it on every connect, so this is for the case the owner
    notices first: a group they were just added to is not in the picker yet.
    """
    now = datetime.now(timezone.utc)
    with system_scope():
        session = _session_row(db)
        session.sync_requested_at = now
        db.commit()

    request.state.audit.add(group_sync_requested=True)
    return get_session(db, request)


@router.get(
    "/internal/whatsapp/commands",
    response_model=GatewayCommands,
    tags=["internal"],
    summary="Work queued for the gateway (HMAC-authenticated)",
)
async def gateway_commands(
    request: Request,
    db: SessionDep,
    x_balaji_signature: str | None = Header(default=None),
    x_balaji_timestamp: str | None = Header(default=None),
) -> GatewayCommands:
    """Hand over any queued commands, clearing them in the same transaction.

    The gateway polls this every few seconds, which is why it does as little as
    possible: one row, one UPDATE, and only when something is actually pending.

    Claim-on-read is deliberate. Leaving the request set until the gateway
    confirms success would mean a gateway that restarts mid-pairing wipes its
    WhatsApp session again on boot, and again after that -- a re-pair loop
    against WhatsApp's servers. Losing a command costs one more press.
    """
    verify_gateway_signature(
        await request.body(), x_balaji_signature, x_balaji_timestamp
    )

    with system_scope():
        session = db.get(WhatsAppSession, 1)
        if session is None:
            return GatewayCommands()
        commands = GatewayCommands(
            pair=session.pair_requested_at is not None,
            sync_groups=session.sync_requested_at is not None,
        )
        if commands.pair or commands.sync_groups:
            session.pair_requested_at = None
            session.sync_requested_at = None
            db.commit()

    return commands


@router.post(
    "/internal/whatsapp/directory",
    tags=["internal"],
    summary="Gateway uploads every group the account is in (HMAC-authenticated)",
)
async def report_directory(request: Request, db: SessionDep) -> dict:
    """Cache the group list so the owner picks names instead of pasting ids.

    Upsert, never wholesale replace: the ``whatsapp_groups`` rows that decide
    what is actually read are keyed on the same jid, and a sync that arrives
    mid-reconnect with a partial list must not empty the picker. Rows for groups
    the account has left simply stop being touched, and the UI ages them out.
    """
    body = await request.body()
    verify_gateway_signature(
        body,
        request.headers.get("x-balaji-signature"),
        request.headers.get("x-balaji-timestamp"),
    )
    payload = DirectoryReport.model_validate_json(body)

    now = datetime.now(timezone.utc)
    with system_scope():
        incoming = {}
        for group in payload.groups:
            jid = group.group_jid.strip()
            # Only groups. A direct chat arriving here would be a gateway bug,
            # and it must never become something the owner can tick and read.
            if jid.endswith("@g.us"):
                incoming[jid] = group

        existing = {
            row.group_jid: row
            for row in db.execute(
                select(WhatsAppGroupCandidate).where(
                    WhatsAppGroupCandidate.group_jid.in_(list(incoming))
                )
            )
            .scalars()
            .all()
        }

        added = 0
        for jid, group in incoming.items():
            name = (group.name or "").strip()
            row = existing.get(jid)
            if row is None:
                db.add(
                    WhatsAppGroupCandidate(
                        group_jid=jid,
                        name=name,
                        participants=group.participants,
                        last_seen_at=now,
                    )
                )
                added += 1
                continue
            # A later sync with no subject yet must not blank a name the owner
            # is already recognising the group by.
            if name:
                row.name = name
            row.participants = group.participants
            row.last_seen_at = now

        session = _session_row(db)
        session.directory_synced_at = now
        db.commit()

    return {"ok": True, "known": len(incoming), "added": added}


@router.get(
    "/whatsapp/available-groups",
    response_model=list[GroupCandidateOut],
    dependencies=[Depends(require("whatsapp.manage"))],
)
def available_groups(
    db: SessionDep,
    q: str | None = Query(default=None, max_length=80),
    watched_only: bool = False,
) -> list[GroupCandidateOut]:
    """Every group the linked account is in, flagged with whether it is watched.

    This is what replaced transcribing ``120363…@g.us`` ids out of a terminal.
    A working brokerage account sits in hundreds of groups, so the list is
    searchable and the watched ones are pinned to the top -- the two things the
    owner is ever doing here is finding one group by name, and checking what is
    already on.
    """
    with system_scope():
        stmt = select(WhatsAppGroupCandidate)
        if q:
            needle = f"%{q.strip().lower()}%"
            stmt = stmt.where(func.lower(WhatsAppGroupCandidate.name).like(needle))
        candidates = db.execute(stmt).scalars().all()

        # Every watched group, including ones no longer in the account's list:
        # a group the account has left is still being read from as far as the
        # ingest webhook is concerned, and the owner needs to see that to
        # switch it off.
        watched = {
            row.group_jid: row
            for row in db.execute(
                select(WhatsAppGroup).where(WhatsAppGroup.deleted_at.is_(None))
            )
            .scalars()
            .all()
        }

    seen = set()
    out: list[GroupCandidateOut] = []
    for row in candidates:
        group = watched.get(row.group_jid)
        seen.add(row.group_jid)
        out.append(
            GroupCandidateOut(
                group_jid=row.group_jid,
                name=row.name or "",
                participants=row.participants,
                last_seen_at=row.last_seen_at,
                watched=group is not None,
                group_id=group.id if group else None,
                is_active=group.is_active if group else None,
            )
        )

    # Watched groups the directory has never heard of -- added by hand before
    # this screen existed, or in a group the account has since left. Dropping
    # them would hide something that is actively being read.
    for jid, group in watched.items():
        if jid in seen:
            continue
        if q and q.strip().lower() not in (group.name or "").lower():
            continue
        out.append(
            GroupCandidateOut(
                group_jid=jid,
                name=group.name,
                participants=0,
                last_seen_at=group.created_at,
                watched=True,
                group_id=group.id,
                is_active=group.is_active,
            )
        )

    if watched_only:
        out = [row for row in out if row.watched]

    # Watched first, then by name. An unnamed group sorts last within its half:
    # its metadata has not synced yet and there is nothing for the owner to
    # recognise it by.
    out.sort(key=lambda r: (not r.watched, not r.name, r.name.lower()))
    return out
