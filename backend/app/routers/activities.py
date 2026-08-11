"""Activities and the owner's live activity feed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.deps import (
    PageDep,
    PrincipalDep,
    ScopedDep,
    SessionDep,
    rate_limit_lists,
)
from app.errors import bad_request, not_found
from app.models import Activity, CallLog, Contact, Property, PropertyInterest
from app.schemas import ActivityCreate, ActivityOut, FeedItem, Paged
from app.serializers import user_names

router = APIRouter(tags=["activities"])

OUTCOME_TONE = {
    "connected": "positive",
    "interested": "positive",
    "callback_requested": "neutral",
    "not_reachable": "neutral",
    "not_interested": "warning",
    "wrong_number": "warning",
}


@router.post("/activities", response_model=ActivityOut, status_code=201)
def create_activity(
    payload: ActivityCreate,
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> ActivityOut:
    """Log a site visit, note, stage change or follow-up against a lead."""
    contact = None
    if payload.contact_id is not None:
        contact = db.execute(
            scoped.contacts().where(Contact.id == payload.contact_id)
        ).scalar_one_or_none()
        if contact is None:
            raise not_found("Contact")

    prop = None
    if payload.property_id is not None:
        prop = db.execute(
            scoped.properties().where(Property.id == payload.property_id)
        ).scalar_one_or_none()
        if prop is None:
            raise not_found("Property")

    if contact is None and prop is None:
        raise bad_request(
            "missing_subject", "An activity needs a contact, a property, or both."
        )

    activity = Activity(
        contact_id=payload.contact_id,
        property_id=payload.property_id,
        user_id=principal.id,
        type=payload.type,
        body=payload.body,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    db.add(activity)

    if contact is not None and payload.type == "site_visit" and contact.stage in (
        "new",
        "contacted",
        "site_visit_scheduled",
    ):
        contact.stage = "visited"
        contact.updated_at = datetime.now(timezone.utc)

    db.commit()

    request.state.audit.set_resource(activity.id)
    request.state.audit.add(
        activity_type=payload.type,
        contact_id=payload.contact_id,
        property_id=payload.property_id,
    )

    names = user_names(db, [principal.id])
    out = ActivityOut.model_validate(activity)
    out.user_name = names.get(principal.id)
    out.contact_name = contact.full_name if contact else None
    out.property_title = prop.title if prop else None
    return out


@router.get(
    "/activities",
    response_model=Paged[ActivityOut],
    dependencies=[Depends(rate_limit_lists)],
)
def list_activities(
    scoped: ScopedDep,
    db: SessionDep,
    page: PageDep,
    request: Request,
    contact_id: int | None = None,
    property_id: int | None = None,
    type: str | None = None,
) -> Paged[ActivityOut]:
    stmt = scoped.activities()
    if contact_id is not None:
        stmt = stmt.where(Activity.contact_id == contact_id)
    if property_id is not None:
        stmt = stmt.where(Activity.property_id == property_id)
    if type:
        stmt = stmt.where(Activity.type == type)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Activity.occurred_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    request.state.audit.add(returned_count=len(rows), total_in_scope=total)

    names = user_names(db, [r.user_id for r in rows])
    contact_ids = {r.contact_id for r in rows if r.contact_id}
    prop_ids = {r.property_id for r in rows if r.property_id}
    contacts = (
        {
            c.id: c.full_name
            for c in db.execute(
                scoped.contacts().where(Contact.id.in_(contact_ids))
            ).scalars()
        }
        if contact_ids
        else {}
    )
    props = (
        {
            p.id: (p.title or f"{p.building or ''} {p.location}".strip())
            for p in db.execute(
                scoped.properties().where(Property.id.in_(prop_ids))
            ).scalars()
        }
        if prop_ids
        else {}
    )

    items = []
    for r in rows:
        item = ActivityOut.model_validate(r)
        item.user_name = names.get(r.user_id)
        item.contact_name = contacts.get(r.contact_id) if r.contact_id else None
        item.property_title = props.get(r.property_id) if r.property_id else None
        items.append(item)

    return Paged[ActivityOut](
        items=items,
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )


@router.get(
    "/activities/feed",
    response_model=list[FeedItem],
    dependencies=[Depends(rate_limit_lists)],
)
def activity_feed(
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
    limit: int = Query(default=50, ge=1, le=50),
    since_hours: int = Query(default=168, ge=1, le=24 * 90),
) -> list[FeedItem]:
    """Live feed of what the firm is doing, newest first.

    For the Owner this is firm-wide. For everyone else the same endpoint returns
    only their own activity -- ROLES_PERMISSIONS.md grants staff "own activity
    only" rather than denying the feed outright, and the scoping layer already
    enforces that, so no separate endpoint is needed.

    Calls, activities and showings live in three tables by design (each event is
    its own immutable row); the merge happens here so the owner reads one
    chronological stream.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    calls = (
        db.execute(
            scoped.call_logs()
            .where(CallLog.created_at >= since)
            .order_by(CallLog.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    acts = (
        db.execute(
            scoped.activities()
            .where(Activity.occurred_at >= since)
            .order_by(Activity.occurred_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    shows = (
        db.execute(
            scoped.property_interests()
            .where(PropertyInterest.shown_at >= since)
            .order_by(PropertyInterest.shown_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    contact_ids = (
        {c.contact_id for c in calls if c.contact_id}
        | {a.contact_id for a in acts if a.contact_id}
        | {s.contact_id for s in shows}
    )
    prop_ids = {a.property_id for a in acts if a.property_id} | {
        s.property_id for s in shows
    }
    user_ids = (
        [c.caller_id for c in calls]
        + [a.user_id for a in acts]
        + [s.shown_by_agent_id for s in shows]
    )

    contacts = (
        {
            c.id: c.full_name
            for c in db.execute(
                scoped.contacts().where(Contact.id.in_(contact_ids))
            ).scalars()
        }
        if contact_ids
        else {}
    )
    props = (
        {
            p.id: (p.title or f"{p.building or ''} {p.location}".strip())
            for p in db.execute(
                scoped.properties().where(Property.id.in_(prop_ids))
            ).scalars()
        }
        if prop_ids
        else {}
    )
    names = user_names(db, user_ids)

    items: list[FeedItem] = []

    for c in calls:
        outcome_label = c.outcome.replace("_", " ").title()
        items.append(
            FeedItem(
                kind="call",
                occurred_at=c.created_at,
                user_id=c.caller_id,
                user_name=names.get(c.caller_id),
                contact_id=c.contact_id,
                contact_name=contacts.get(c.contact_id) if c.contact_id else None,
                title=f"Called {contacts.get(c.contact_id, 'a lead')}",
                detail=c.notes or outcome_label,
                outcome=c.outcome,
                temperature=c.temperature,
                flagged=bool(c.flagged_for_owner),
                tone="signal"
                if c.flagged_for_owner
                else OUTCOME_TONE.get(c.outcome, "neutral"),  # type: ignore[arg-type]
            )
        )

    for s in shows:
        prop_label = props.get(s.property_id, "a property")
        items.append(
            FeedItem(
                kind="showing",
                occurred_at=s.shown_at,
                user_id=s.shown_by_agent_id,
                user_name=names.get(s.shown_by_agent_id),
                contact_id=s.contact_id,
                contact_name=contacts.get(s.contact_id),
                property_id=s.property_id,
                property_title=prop_label,
                title=f"Showed {prop_label} to {contacts.get(s.contact_id, 'a client')}",
                detail=(s.interest_level or "").replace("_", " ").title() or None,
                tone="positive",
            )
        )

    # Site visits already appear as showings; including their mirrored activity
    # row too would double every visit in the feed.
    for a in acts:
        if a.type == "site_visit":
            continue
        items.append(
            FeedItem(
                kind="activity",
                occurred_at=a.occurred_at,
                user_id=a.user_id,
                user_name=names.get(a.user_id),
                contact_id=a.contact_id,
                contact_name=contacts.get(a.contact_id) if a.contact_id else None,
                property_id=a.property_id,
                property_title=props.get(a.property_id) if a.property_id else None,
                title={
                    "stage_change": "Stage updated",
                    "note": "Note added",
                    "follow_up": "Follow-up logged",
                }.get(a.type, a.type.replace("_", " ").title()),
                detail=a.body,
                tone="neutral",
            )
        )

    items.sort(key=lambda i: i.occurred_at, reverse=True)
    items = items[:limit]
    request.state.audit.add(returned_count=len(items), feed=True)
    return items
