from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from app.db import system_scope
from app.deps import PrincipalDep, ScopedDep, SessionDep, require
from app.errors import bad_request, not_found
from app.models import Activity, CallLog, Contact, PropertyInterest, Task, User
from app.schemas import (
    ReassignLeadsRequest,
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
