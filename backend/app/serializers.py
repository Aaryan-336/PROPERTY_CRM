"""Row -> response conversion, including the masking gate for contacts."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db import SCOPE_MARKER, system_scope
from app.masking import (
    contacts_with_logged_interaction,
    mask_email,
    mask_phone,
    should_unmask,
)
from app.models import Activity, CallLog, Contact, User
from app.schemas import ContactOut
from app.scoping import Principal


def user_names(db: DbSession, user_ids: Sequence[int | None]) -> dict[int, str]:
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    stmt = (
        select(User.id, User.name)
        .where(User.id.in_(ids))
        .execution_options(**{SCOPE_MARKER: True})
    )
    # Staff names are not confidential within the firm -- an agent already sees
    # colleague names on shared inventory. Only lead data is scoped.
    return {row[0]: row[1] for row in db.execute(stmt)}


def last_activity_map(
    db: DbSession, contact_ids: Sequence[int]
) -> dict[int, object]:
    """Most recent touch per contact, across calls and activities."""
    ids = [i for i in contact_ids if i]
    if not ids:
        return {}

    calls = db.execute(
        select(CallLog.contact_id, func.max(CallLog.created_at))
        .where(CallLog.contact_id.in_(ids))
        .group_by(CallLog.contact_id)
        .execution_options(**{SCOPE_MARKER: True})
    ).all()
    acts = db.execute(
        select(Activity.contact_id, func.max(Activity.occurred_at))
        .where(Activity.contact_id.in_(ids))
        .group_by(Activity.contact_id)
        .execution_options(**{SCOPE_MARKER: True})
    ).all()

    out: dict[int, object] = {}
    for cid, ts in list(calls) + list(acts):
        if cid is None or ts is None:
            continue
        current = out.get(cid)
        if current is None or ts > current:
            out[cid] = ts
    return out


def serialize_contacts(
    db: DbSession,
    principal: Principal,
    rows: Sequence[Contact],
    *,
    include_last_activity: bool = True,
) -> list[ContactOut]:
    """Serialize contacts, masking phone/email where the role has not earned it.

    The masked value is produced here, so the raw digits are never part of the
    response body at all -- a network inspector shows the mask, not the number.
    """
    if not rows:
        return []

    ids = [c.id for c in rows]
    worked = contacts_with_logged_interaction(db, principal, ids)
    names = user_names(db, [c.owner_id for c in rows])
    last_seen = last_activity_map(db, ids) if include_last_activity else {}
    assignees = assignee_map(db, ids)

    out: list[ContactOut] = []
    for c in rows:
        unmask = should_unmask(principal, c.phone_masked, c.id in worked)
        out.append(
            ContactOut(
                id=c.id,
                first_name=c.first_name,
                last_name=c.last_name,
                email=c.email if unmask else mask_email(c.email),
                phone=c.phone if unmask else mask_phone(c.phone),
                contact_details_masked=not unmask,
                lead_source=c.lead_source,
                campaign=c.campaign,
                budget_min=c.budget_min,
                budget_max=c.budget_max,
                preferred_locations=c.preferred_locations,
                property_type_interest=c.property_type_interest,
                bhk=c.bhk,
                buyer_type=c.buyer_type,
                remarks=c.remarks,
                lead_score=c.lead_score,
                stage=c.stage,
                is_lead=c.is_lead,
                batch_id=c.batch_id,
                assignees=assignees.get(c.id, []),
                owner_id=c.owner_id,
                owner_name=names.get(c.owner_id) if c.owner_id else None,
                created_at=c.created_at,
                updated_at=c.updated_at,
                last_activity_at=last_seen.get(c.id),  # type: ignore[arg-type]
            )
        )
    return out


def serialize_contact(
    db: DbSession, principal: Principal, row: Contact
) -> ContactOut:
    return serialize_contacts(db, principal, [row])[0]


def assignee_map(db: DbSession, contact_ids: list[int]) -> dict[int, list]:
    """Extra staff per contact, for a whole page in one query.

    Per-row lookups would make a 50-lead page 50 extra round trips; most leads
    have no assignees at all, so the map is usually small.
    """
    from app.models import ContactAssignment
    from app.schemas import Assignee

    if not contact_ids:
        return {}

    out: dict[int, list] = {}
    with system_scope():
        rows = db.execute(
            select(ContactAssignment, User)
            .join(User, User.id == ContactAssignment.user_id)
            .where(ContactAssignment.contact_id.in_(contact_ids))
            .order_by(ContactAssignment.created_at.desc())
        ).all()
    for assignment, user in rows:
        out.setdefault(assignment.contact_id, []).append(
            Assignee(
                user_id=assignment.user_id,
                name=user.name,
                role=user.role,
                created_at=assignment.created_at,
                note=assignment.note,
            )
        )
    return out
