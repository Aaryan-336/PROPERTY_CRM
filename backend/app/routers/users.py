from __future__ import annotations

import secrets

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.db import system_scope
from app.deps import PrincipalDep, ScopedDep, SessionDep, require
from app.errors import ApiError, bad_request, not_found
from app.models import (
    ROLE_OWNER,
    Activity,
    CallLog,
    Contact,
    PropertyInterest,
    Task,
    User,
)
from app.schemas import (
    PasswordReset,
    PasswordResetResponse,
    ReassignLeadsRequest,
    StaffPerformance,
    TeamPerformance,
    ReassignLeadsResponse,
    UserCreate,
    UserOut,
    UserUpdate,
    UserWorkload,
)
from app.security import hash_password, revoke_all_for_user

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(scoped: ScopedDep, db: SessionDep) -> list[UserOut]:
    """Owner sees all staff; every other role sees only themselves."""
    rows = db.execute(scoped.users().order_by(User.name)).scalars().all()
    return [UserOut.model_validate(u) for u in rows]


@router.post(
    "/users",
    response_model=UserOut,
    status_code=201,
    dependencies=[Depends(require("users.manage"))],
)
def create_user(payload: UserCreate, db: SessionDep, request: Request) -> UserOut:
    email = payload.email.strip().lower()
    # Uniqueness check, not a data read: must consider rows the caller's scope
    # would hide (e.g. a deactivated account still holding the address).
    with system_scope():
        exists = db.execute(select(User.id).where(User.email == email)).first()
    if exists:
        raise bad_request("email_taken", "A user with that email already exists.")

    user = User(
        name=payload.name.strip(),
        email=email,
        phone=payload.phone,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_available=True,
    )
    db.add(user)
    db.commit()

    request.state.audit.set_resource(user.id)
    request.state.audit.add(created_role=user.role, created_email=email)
    return UserOut.model_validate(user)


@router.get(
    "/users/workload",
    response_model=list[UserWorkload],
    dependencies=[Depends(require("users.manage"))],
)
def team_workload(scoped: ScopedDep, db: SessionDep) -> list[UserWorkload]:
    """Every staff member with what they are currently carrying.

    Exists so the owner's "remove this person" decision is an informed one.
    Deactivating a cold caller who holds 40 live leads strands all of them
    until someone notices, so the count belongs on the screen where the
    decision is made -- alongside :func:`reassign_leads`, which is the fix.

    Deactivated staff are included: the owner needs to see that a departed
    agent still owns leads nobody has picked up.
    """
    users = (
        db.execute(scoped.users(include_deactivated=True).order_by(User.name))
        .scalars()
        .all()
    )
    ids = [u.id for u in users]
    if not ids:
        return []

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    def tally(stmt) -> dict[int, int]:
        return {row[0]: row[1] for row in db.execute(stmt)}

    # Aggregates over the whole firm, which is precisely the Owner's scope --
    # this endpoint is already gated to `users.manage`.
    with system_scope():
        leads = tally(
            select(Contact.owner_id, func.count())
            .where(Contact.owner_id.in_(ids))
            .where(Contact.deleted_at.is_(None))
            .where(Contact.stage.not_in(("closed", "lost")))
            .group_by(Contact.owner_id)
        )
        open_tasks = tally(
            select(Task.assigned_to, func.count())
            .where(Task.assigned_to.in_(ids))
            .where(Task.status == "pending")
            .group_by(Task.assigned_to)
        )
        overdue = tally(
            select(Task.assigned_to, func.count())
            .where(Task.assigned_to.in_(ids))
            .where(Task.status == "pending")
            .where(Task.due_at.is_not(None))
            .where(Task.due_at <= datetime.now(timezone.utc))
            .group_by(Task.assigned_to)
        )
        calls = tally(
            select(CallLog.caller_id, func.count())
            .where(CallLog.caller_id.in_(ids))
            .where(CallLog.created_at >= week_ago)
            .group_by(CallLog.caller_id)
        )
        showings = tally(
            select(PropertyInterest.shown_by_agent_id, func.count())
            .where(PropertyInterest.shown_by_agent_id.in_(ids))
            .where(PropertyInterest.shown_at >= week_ago)
            .group_by(PropertyInterest.shown_by_agent_id)
        )
        last_call = {
            row[0]: row[1]
            for row in db.execute(
                select(CallLog.caller_id, func.max(CallLog.created_at))
                .where(CallLog.caller_id.in_(ids))
                .group_by(CallLog.caller_id)
            )
        }

    return [
        UserWorkload(
            user=UserOut.model_validate(u),
            active_leads=leads.get(u.id, 0),
            open_tasks=open_tasks.get(u.id, 0),
            overdue_tasks=overdue.get(u.id, 0),
            calls_last_7d=calls.get(u.id, 0),
            showings_last_7d=showings.get(u.id, 0),
            last_active_at=last_call.get(u.id),
        )
        for u in users
    ]


@router.get(
    "/team/performance",
    response_model=TeamPerformance,
    dependencies=[Depends(require("users.manage"))],
)
def team_performance(
    scoped: ScopedDep,
    db: SessionDep,
    days: int = Query(default=30, ge=1, le=365),
) -> TeamPerformance:
    """Per-person call, showing and conversion numbers over a window.

    The PRD's owner story is "I want to see exactly which agent showed which
    property to which client, and spot underperformance". The activity feed
    answers the first half; this answers the second, by putting everyone's
    numbers side by side over the same period.

    Everything is computed with grouped aggregates rather than per-user
    queries, so the cost does not scale with headcount.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    now = datetime.now(timezone.utc)

    users = (
        db.execute(scoped.users(include_deactivated=True).order_by(User.name))
        .scalars()
        .all()
    )
    ids = [u.id for u in users]
    if not ids:
        return TeamPerformance(days=days, since=since, staff=[])

    def pairs(stmt) -> dict:
        return {(row[0], row[1]): row[2] for row in db.execute(stmt)}

    def tally(stmt) -> dict[int, int]:
        return {row[0]: row[1] for row in db.execute(stmt)}

    # Owner-scoped by the capability above; these are firm-wide aggregates.
    with system_scope():
        by_outcome = pairs(
            select(CallLog.caller_id, CallLog.outcome, func.count())
            .where(CallLog.caller_id.in_(ids))
            .where(CallLog.created_at >= since)
            .group_by(CallLog.caller_id, CallLog.outcome)
        )
        escalations = tally(
            select(CallLog.caller_id, func.count())
            .where(CallLog.caller_id.in_(ids))
            .where(CallLog.created_at >= since)
            .where(CallLog.flagged_for_owner.is_(True))
            .group_by(CallLog.caller_id)
        )
        showings = tally(
            select(PropertyInterest.shown_by_agent_id, func.count())
            .where(PropertyInterest.shown_by_agent_id.in_(ids))
            .where(PropertyInterest.shown_at >= since)
            .group_by(PropertyInterest.shown_by_agent_id)
        )
        by_stage = pairs(
            select(Contact.owner_id, Contact.stage, func.count())
            .where(Contact.owner_id.in_(ids))
            .where(Contact.deleted_at.is_(None))
            .group_by(Contact.owner_id, Contact.stage)
        )
        tasks_open = tally(
            select(Task.assigned_to, func.count())
            .where(Task.assigned_to.in_(ids))
            .where(Task.status == "pending")
            .group_by(Task.assigned_to)
        )
        tasks_overdue = tally(
            select(Task.assigned_to, func.count())
            .where(Task.assigned_to.in_(ids))
            .where(Task.status == "pending")
            .where(Task.due_at.is_not(None))
            .where(Task.due_at <= now)
            .group_by(Task.assigned_to)
        )
        last_active = tally(
            select(CallLog.caller_id, func.max(CallLog.created_at))
            .where(CallLog.caller_id.in_(ids))
            .group_by(CallLog.caller_id)
        )

        # Median hours from a lead being created to this person's first call on
        # it. The inner query finds each lead's first call; the outer takes the
        # median per caller, which Postgres does natively.
        first_call = (
            select(
                CallLog.caller_id.label("caller_id"),
                CallLog.contact_id.label("contact_id"),
                func.min(CallLog.created_at).label("first_at"),
            )
            .where(CallLog.caller_id.in_(ids))
            .where(CallLog.created_at >= since)
            .where(CallLog.contact_id.is_not(None))
            .group_by(CallLog.caller_id, CallLog.contact_id)
            .subquery()
        )
        response = {
            row[0]: float(row[1])
            for row in db.execute(
                select(
                    first_call.c.caller_id,
                    func.percentile_cont(0.5)
                    .within_group(
                        func.extract(
                            "epoch", first_call.c.first_at - Contact.created_at
                        )
                        / 3600.0
                    )
                    .label("median_hours"),
                )
                .select_from(first_call)
                .join(Contact, Contact.id == first_call.c.contact_id)
                .group_by(first_call.c.caller_id)
            )
            if row[1] is not None
        }

    staff: list[StaffPerformance] = []
    for user in users:
        outcomes = {
            outcome: count
            for (uid, outcome), count in by_outcome.items()
            if uid == user.id and outcome
        }
        calls = sum(outcomes.values())
        # "Reached a human" — the outcomes that represent an actual
        # conversation, which is what a caller is really measured on.
        connected = sum(
            outcomes.get(o, 0)
            for o in ("connected", "interested", "callback_requested")
        )

        stages = {
            stage: count
            for (uid, stage), count in by_stage.items()
            if uid == user.id and stage
        }
        assigned = sum(stages.values())
        closed = stages.get("closed", 0)

        staff.append(
            StaffPerformance(
                user=UserOut.model_validate(user),
                calls=calls,
                calls_by_outcome=outcomes,
                connected=connected,
                connect_rate=round(connected / calls, 4) if calls else None,
                showings=showings.get(user.id, 0),
                escalations=escalations.get(user.id, 0),
                leads_assigned=assigned,
                leads_by_stage=stages,
                closed=closed,
                conversion_rate=round(closed / assigned, 4) if assigned else None,
                tasks_open=tasks_open.get(user.id, 0),
                tasks_overdue=tasks_overdue.get(user.id, 0),
                median_response_hours=(
                    round(response[user.id], 2) if user.id in response else None
                ),
                last_active_at=last_active.get(user.id),
            )
        )

    return TeamPerformance(
        days=days,
        since=since,
        staff=staff,
        total_calls=sum(s.calls for s in staff),
        total_showings=sum(s.showings for s in staff),
        total_closed=sum(s.closed for s in staff),
    )


@router.post(
    "/users/{user_id}/reassign-leads",
    response_model=ReassignLeadsResponse,
    dependencies=[Depends(require("users.manage"))],
)
def reassign_leads(
    user_id: int,
    payload: ReassignLeadsRequest,
    db: SessionDep,
    principal: PrincipalDep,
    scoped: ScopedDep,
    request: Request,
) -> ReassignLeadsResponse:
    """Move every live lead from one staff member to another.

    The companion to deactivation. Removing a staff member without this leaves
    their whole book owned by an account that can no longer log in -- the leads
    stop appearing in anyone's queue and quietly rot, which is the exact
    failure the PRD's "no owner visibility" problem describes.

    Closed and lost leads stay put: they are history, and moving them would
    rewrite who actually worked the deal in every report the owner runs.
    """
    if user_id == payload.to_user_id:
        raise bad_request(
            "same_user", "Choose a different staff member to receive the leads."
        )

    source = db.execute(
        scoped.users(include_deactivated=True).where(User.id == user_id)
    ).scalar_one_or_none()
    if source is None:
        raise not_found("User")

    target = db.execute(
        scoped.users().where(User.id == payload.to_user_id)
    ).scalar_one_or_none()
    if target is None:
        raise bad_request(
            "unknown_user", "That staff member does not exist or is deactivated."
        )

    now = datetime.now(timezone.utc)
    with system_scope():
        rows = (
            db.execute(
                select(Contact)
                .where(Contact.owner_id == user_id)
                .where(Contact.deleted_at.is_(None))
                .where(Contact.stage.not_in(("closed", "lost")))
            )
            .scalars()
            .all()
        )
        moved_ids = [c.id for c in rows]
        for contact in rows:
            contact.owner_id = target.id
            contact.updated_at = now
            # Each move is its own activity row, so the lead's timeline shows
            # the handover rather than the new owner appearing from nowhere.
            db.add(
                Activity(
                    contact_id=contact.id,
                    user_id=principal.id,
                    type="note",
                    body=(
                        f"Reassigned from {source.name} to {target.name}"
                        + (f" — {payload.reason}" if payload.reason else "")
                    ),
                    occurred_at=now,
                )
            )
    db.commit()

    request.state.audit.action_override = "reassign"
    request.state.audit.add(
        from_user_id=user_id,
        to_user_id=target.id,
        moved_count=len(moved_ids),
        moved_contact_ids=moved_ids[:100],
        reason=payload.reason,
    )
    return ReassignLeadsResponse(
        moved=len(moved_ids), from_user_id=user_id, to_user_id=target.id
    )


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require("users.manage"))],
)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: SessionDep,
    principal: PrincipalDep,
    scoped: ScopedDep,
    request: Request,
) -> UserOut:
    user = db.execute(
        scoped.users(include_deactivated=True).where(User.id == user_id)
    ).scalar_one_or_none()
    if user is None:
        raise not_found("User")

    fields = payload.model_dump(exclude_unset=True)
    deactivate = fields.pop("deactivate", None)

    before = {k: getattr(user, k) for k in fields}
    for key, value in fields.items():
        setattr(user, key, value)

    revoked = 0
    if deactivate is True:
        if user.id == principal.id:
            raise bad_request(
                "cannot_deactivate_self",
                "You cannot deactivate your own account.",
            )
        user.deleted_at = datetime.now(timezone.utc)
        user.is_available = False
        # SECURITY_MODEL.md: deactivation must invalidate outstanding tokens,
        # not merely block future logins. Otherwise a departing agent keeps
        # API access for the remaining life of their JWT.
        revoked = revoke_all_for_user(db, user.id)
    elif deactivate is False and user.deleted_at is not None:
        user.deleted_at = None
        user.is_available = True

    db.commit()

    request.state.audit.record_changes(before, fields)
    request.state.audit.add(
        deactivated=bool(deactivate), sessions_revoked=revoked
    )
    return UserOut.model_validate(user)


@router.post(
    "/users/{user_id}/reset-password",
    response_model=PasswordResetResponse,
    dependencies=[Depends(require("users.manage"))],
)
def reset_password(
    user_id: int,
    payload: PasswordReset,
    principal: PrincipalDep,
    db: SessionDep,
    request: Request,
) -> PasswordResetResponse:
    """Owner sets a new password for a staff member who has lost theirs.

    There is no email on this system and no reset link, so somebody has to be
    able to do this or a forgotten password means a dead account. That somebody
    is the Owner, and every use is audited: an owner who can silently take over
    a cold caller's account is exactly the sort of thing the audit log exists
    to make non-silent.

    Refuses to touch any Owner, including the caller's own account. Two owners
    resetting each other is a standoff rather than a hierarchy — and allowing
    self-reset here would quietly undo `/auth/change-password`, which demands
    the current password precisely so that a borrowed unlocked laptop cannot
    take the account permanently. An owner changing their own password goes
    through that endpoint and proves they know the old one.

    The recovery path for a genuinely locked-out owner is
    `app/create_owner.py --force` with database access — a deliberately higher
    bar, and one that cannot be reached from a logged-in browser at all.
    """
    with system_scope():
        user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise not_found("User")

    if user.role == ROLE_OWNER:
        raise ApiError(
            403,
            "cannot_reset_owner",
            "An Owner's password cannot be reset from here. Use Change "
            "password, which requires the current one.",
        )

    password = payload.new_password or secrets.token_urlsafe(12)
    user.password_hash = hash_password(password)
    db.flush()

    # Every one of their sessions dies. A reset usually means the account is
    # suspected compromised or the person has left the desk; leaving live
    # tokens working would defeat it.
    revoked = revoke_all_for_user(db, user.id)
    db.commit()

    request.state.audit.set_resource(user.id)
    request.state.audit.add(
        reset_by=principal.id,
        was_generated=payload.new_password is None,
        sessions_revoked=revoked,
    )

    return PasswordResetResponse(
        user_id=user.id,
        name=user.name,
        generated_password=password if payload.new_password is None else None,
        sessions_revoked=revoked,
    )
