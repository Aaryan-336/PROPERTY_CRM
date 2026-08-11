"""Contact phone/email masking.

SECURITY_MODEL.md is specific about the mechanism: "the raw value should not
even be sent to the client for a masked contact, not just visually hidden by
CSS, since a network inspector would defeat CSS-only masking." So masking
happens here, during serialization, and the unmasked string never enters the
response body.

The rule: a contact with ``phone_masked = true`` stays masked for Agent and
Cold Caller until that user has logged a qualifying interaction on it -- a
call or a site visit. Owner always sees the real value. The point is to make a
stolen lead list worth less than the work required to unlock it.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select, union
from sqlalchemy.orm import Session as DbSession

from app.db import SCOPE_MARKER
from app.models import Activity, CallLog
from app.scoping import Principal

QUALIFYING_ACTIVITY_TYPES = ("site_visit",)


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = [c for c in phone if c.isdigit()]
    if len(digits) <= 4:
        return "•" * len(digits)
    return "•" * (len(digits) - 4) + "".join(digits[-4:])


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    keep = local[0] if local else ""
    return f"{keep}{'•' * max(len(local) - 1, 3)}@{domain}"


def contacts_with_logged_interaction(
    db: DbSession, principal: Principal, contact_ids: Iterable[int]
) -> set[int]:
    """Which of ``contact_ids`` this user has personally worked.

    Batched deliberately: a list endpoint resolves the whole page in one query
    rather than one query per row.
    """
    ids = [i for i in contact_ids if i is not None]
    if not ids:
        return set()

    calls = (
        select(CallLog.contact_id)
        .where(CallLog.caller_id == principal.id, CallLog.contact_id.in_(ids))
    )
    visits = (
        select(Activity.contact_id)
        .where(
            Activity.user_id == principal.id,
            Activity.contact_id.in_(ids),
            Activity.type.in_(QUALIFYING_ACTIVITY_TYPES),
        )
    )
    stmt = union(calls, visits).execution_options(**{SCOPE_MARKER: True})
    # Safe without a role filter: the id list is already the caller's own
    # scoped page, and both branches additionally filter to their own user id.
    return {row[0] for row in db.execute(stmt) if row[0] is not None}


def should_unmask(
    principal: Principal, phone_masked: bool | None, has_interaction: bool
) -> bool:
    if principal.sees_everything:
        return True
    if not phone_masked:
        return True
    return has_interaction
