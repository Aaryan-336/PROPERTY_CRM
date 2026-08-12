"""Call logging and the cold-caller queue.

One-tap call logging is the highest-frequency write in the product, so the POST
body is deliberately small: contact, outcome, and optionally temperature, a
note, a flag, and a callback time.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Integer, and_, case, func, literal, select

from app.deps import (
    PageDep,
    PrincipalDep,
    ScopedDep,
    SessionDep,
    rate_limit_lists,
    require,
)
from app.errors import not_found
from app.models import FOLLOW_UP_OUTCOMES, CallLog, Contact, Task
from app.push import send_to_users
from app.rbac import assert_capability
from app.schemas import (
    CallCreate,
    CallCreateResponse,
    CallOut,
    Paged,
    QueueContact,
    QueueItem,
    TaskOut,
)
from app.serializers import serialize_contacts, user_names
from app.scoping import ScopedQuery

router = APIRouter(tags=["calls"])

# Outcomes that take a lead out of the calling rotation.
DEAD_OUTCOMES = ("not_interested", "wrong_number")
CLOSED_STAGES = ("closed", "lost")

DEFAULT_CALLBACK_HOURS = 24


def _owner_ids(db: SessionDep) -> list[int]:
    from app.db import SCOPE_MARKER
    from app.models import ROLE_OWNER, User

    return [
        row[0]
        for row in db.execute(
            select(User.id)
            .where(User.role == ROLE_OWNER, User.deleted_at.is_(None))
            .execution_options(**{SCOPE_MARKER: True})
        )
    ]


@router.post("/calls", response_model=CallCreateResponse, status_code=201)
def log_call(
    payload: CallCreate,
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> CallCreateResponse:
    assert_capability(principal, "calls.log")

    contact = db.execute(
        scoped.contacts().where(Contact.id == payload.contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise not_found("Contact")

    call = CallLog(
        contact_id=contact.id,
        caller_id=principal.id,
        outcome=payload.outcome,
        temperature=payload.temperature,
        notes=payload.notes,
        flagged_for_owner=payload.flagged_for_owner,
        marked_lead=payload.marked_lead,
        follow_up_at=payload.follow_up_at,
    )
    db.add(call)
    db.flush()

    # A first logged call is what unmasks the contact's number for this user
    # (see app/masking.py) -- do the work, earn the detail.
    if contact.stage == "new":
        contact.stage = "contacted"
        contact.updated_at = datetime.now(timezone.utc)

    # The one path by which an imported number becomes a lead. Deliberately a
    # separate judgement from the outcome: a caller can log fifty "interested"
    # results on a bought list and none of them belong in the pipeline until
    # someone says so. One-way — un-flagging is a reassignment decision for the
    # owner, not something to bury in a call form.
    promoted = payload.marked_lead and not contact.is_lead
    if promoted:
        contact.is_lead = True
        contact.updated_at = datetime.now(timezone.utc)

    follow_up: Task | None = None
    if payload.outcome in FOLLOW_UP_OUTCOMES or payload.follow_up_at:
        due = payload.follow_up_at or datetime.now(timezone.utc) + timedelta(
            hours=DEFAULT_CALLBACK_HOURS
        )
        follow_up = Task(
            contact_id=contact.id,
            assigned_to=principal.id,
            created_by=principal.id,
            title=f"Follow up with {contact.full_name}"
            + (" (callback requested)" if payload.outcome == "callback_requested" else ""),
            due_at=due,
            status="pending",
            source_call_log_id=call.id,
        )
        db.add(follow_up)
        call.follow_up_at = due

    db.commit()

    request.state.audit.set_resource(call.id)
    request.state.audit.add(
        contact_id=contact.id,
        outcome=payload.outcome,
        temperature=payload.temperature,
        flagged_for_owner=payload.flagged_for_owner,
        marked_lead=payload.marked_lead,
        promoted_to_lead=promoted,
        batch_id=contact.batch_id,
        follow_up_task_created=follow_up is not None,
    )

    if payload.flagged_for_owner:
        send_to_users(
            db,
            _owner_ids(db),
            title="Lead escalated",
            body=f"{principal.name} flagged {contact.full_name} — {payload.outcome.replace('_', ' ')}",
            url="/escalations",
            tag="escalation",
        )

    names = user_names(db, [principal.id])
    call_out = CallOut.model_validate(call)
    call_out.caller_name = names.get(principal.id)
    call_out.contact_name = contact.full_name

    task_out = None
    if follow_up is not None:
        task_out = TaskOut.model_validate(follow_up)
        task_out.contact_name = contact.full_name
        task_out.assigned_to_name = names.get(principal.id)

    return CallCreateResponse(call=call_out, follow_up_task=task_out)


@router.get(
    "/calls",
    response_model=Paged[CallOut],
    dependencies=[Depends(rate_limit_lists)],
)
def list_calls(
    scoped: ScopedDep,
    db: SessionDep,
    page: PageDep,
    request: Request,
    contact_id: int | None = None,
    flagged: bool | None = None,
) -> Paged[CallOut]:
    stmt = scoped.call_logs()
    if contact_id is not None:
        stmt = stmt.where(CallLog.contact_id == contact_id)
    if flagged is not None:
        stmt = stmt.where(CallLog.flagged_for_owner.is_(flagged))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(CallLog.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    request.state.audit.add(returned_count=len(rows), total_in_scope=total)

    return Paged[CallOut](
        items=_serialize_calls(db, scoped, list(rows)),
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )


@router.get(
    "/owner/escalations",
    response_model=Paged[CallOut],
    dependencies=[Depends(require("escalations.receive"))],
)
def list_escalations(
    scoped: ScopedDep, db: SessionDep, page: PageDep, request: Request
) -> Paged[CallOut]:
    """The owner's inbox of calls a staff member flagged for attention."""
    stmt = scoped.call_logs().where(CallLog.flagged_for_owner.is_(True))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(CallLog.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    request.state.audit.add(returned_count=len(rows), total_in_scope=total)
    return Paged[CallOut](
        items=_serialize_calls(db, scoped, list(rows)),
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )


@router.get(
    "/call-queue",
    response_model=Paged[QueueItem],
    dependencies=[Depends(rate_limit_lists)],
)
def call_queue(
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> Paged[QueueItem]:
    """The cold caller's prioritized queue, scoped to their assigned leads.

    Ordering, in the sequence agreed for Phase 1:

    1. an overdue callback -- a promise already broken is the costliest miss
    2. a lead last marked hot
    3. a lead never called
    4. lead score, then age

    Leads that are closed, lost, not interested, or a wrong number drop out.
    Every row carries the reason it surfaced, so the caller can see why.

    Paged, and returns the true total. The per-request cap stays (it is the
    anti-scraping control from SECURITY_MODEL.md §4), but a caller handed a
    list of 300 imported leads has to be able to work through all of them --
    and, just as importantly, to see that there are 300. Capping at 50 with no
    total made a bulk import look like it had silently failed, because the
    first page is dominated by older leads with overdue callbacks.
    """
    now = datetime.now(timezone.utc)

    latest = (
        scoped.call_logs()
        .distinct(CallLog.contact_id)
        .order_by(CallLog.contact_id, CallLog.created_at.desc())
        .subquery()
    )
    due = (
        scoped.tasks()
        .with_only_columns(
            Task.contact_id.label("contact_id"),
            func.min(Task.due_at).label("due_at"),
        )
        .where(Task.status == "pending")
        .group_by(Task.contact_id)
        .subquery()
    )

    overdue = and_(due.c.due_at.is_not(None), due.c.due_at <= now)
    priority = case(
        (overdue, literal(1)),
        (latest.c.temperature == "hot", literal(2)),
        (latest.c.id.is_(None), literal(3)),
        else_=literal(4),
    ).cast(Integer)

    stmt = (
        scoped.contacts()
        .add_columns(
            priority.label("priority"),
            due.c.due_at.label("due_at"),
            latest.c.outcome.label("last_outcome"),
            latest.c.temperature.label("last_temperature"),
            latest.c.created_at.label("last_called_at"),
        )
        .outerjoin(latest, latest.c.contact_id == Contact.id)
        .outerjoin(due, due.c.contact_id == Contact.id)
        .where(Contact.stage.not_in(CLOSED_STAGES))
        .where(
            (latest.c.outcome.is_(None))
            | (latest.c.outcome.not_in(DEAD_OUTCOMES))
        )
        .order_by(
            priority,
            due.c.due_at.asc().nulls_last(),
            Contact.lead_score.desc(),
            Contact.created_at.asc(),
        )
    )

    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()

    rows = db.execute(stmt.limit(limit).offset(offset)).all()

    request.state.audit.add(
        returned_count=len(rows), total_in_queue=total, queue=True
    )

    reasons = {
        1: "Callback overdue",
        2: "Hot lead",
        3: "New lead — never called",
        4: "Due for a touch",
    }

    items: list[QueueItem] = []
    for contact, prio, due_at, _outcome, _temp, _called in rows:
        items.append(
            QueueItem(
                # Name and number only. The queue is a calling surface, not a
                # window onto the lead book -- see schemas.QueueContact.
                contact=QueueContact(
                    id=contact.id,
                    first_name=contact.first_name,
                    last_name=contact.last_name,
                    phone=contact.phone,
                ),
                reason=reasons.get(int(prio), "Queued"),
                priority=int(prio),
                due_at=due_at,
            )
        )

    return Paged[QueueItem](
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


def _serialize_calls(
    db: SessionDep, scoped: ScopedQuery, rows: list[CallLog]
) -> list[CallOut]:
    if not rows:
        return []
    names = user_names(db, [r.caller_id for r in rows])
    contact_ids = {r.contact_id for r in rows if r.contact_id}
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
    out = []
    for r in rows:
        item = CallOut.model_validate(r)
        item.caller_name = names.get(r.caller_id)
        item.contact_name = contacts.get(r.contact_id) if r.contact_id else None
        out.append(item)
    return out
