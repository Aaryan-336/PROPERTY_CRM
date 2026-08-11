"""Duplicate detection for new contacts (FEATURE_LIST P1).

Exact phone match plus fuzzy name match, per the feature list. Runs against the
*whole* contact table rather than the caller's scope on purpose: an Agent must
not be able to silently re-create a lead that already belongs to a colleague,
which is one of the ways lead ownership gets quietly rewritten. To avoid that
check itself becoming a lookup oracle for other agents' leads, a candidate the
caller cannot see is returned with its name and owner withheld.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db import system_scope
from app.models import Contact, User
from app.schemas import DuplicateCandidate
from app.scoping import Principal

NAME_MATCH_THRESHOLD = 88


@dataclass
class Candidate:
    contact: Contact
    match: str
    score: int


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    # Indian numbers are commonly written with and without the country code;
    # compare on the last 10 digits so both forms collide.
    return digits[-10:] if len(digits) >= 10 else digits or None


def find_duplicates(
    db: DbSession, first_name: str, last_name: str | None, phone: str | None
) -> list[Candidate]:
    normalized = normalize_phone(phone)
    full_name = f"{first_name} {last_name or ''}".strip().lower()

    with system_scope():
        rows = db.execute(
            select(Contact).where(Contact.deleted_at.is_(None))
        ).scalars().all()

    candidates: list[Candidate] = []
    for row in rows:
        if normalized and normalize_phone(row.phone) == normalized:
            candidates.append(Candidate(row, "phone_exact", 100))
            continue
        other = f"{row.first_name} {row.last_name or ''}".strip().lower()
        score = int(fuzz.token_sort_ratio(full_name, other))
        if score >= NAME_MATCH_THRESHOLD:
            candidates.append(Candidate(row, "name_fuzzy", score))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:5]


def to_response(
    db: DbSession, principal: Principal, candidates: list[Candidate]
) -> list[DuplicateCandidate]:
    owner_ids = {c.contact.owner_id for c in candidates if c.contact.owner_id}
    with system_scope():
        names = (
            {
                row[0]: row[1]
                for row in db.execute(
                    select(User.id, User.name).where(User.id.in_(owner_ids))
                )
            }
            if owner_ids
            else {}
        )

    out: list[DuplicateCandidate] = []
    for c in candidates:
        visible = principal.sees_everything or c.contact.owner_id == principal.id
        digits = re.sub(r"\D", "", c.contact.phone or "")
        out.append(
            DuplicateCandidate(
                id=c.contact.id,
                # Withheld for out-of-scope rows: enough to say "this lead is
                # already in the system and is not yours", not enough to read
                # a colleague's book.
                name=(
                    f"{c.contact.first_name} {c.contact.last_name or ''}".strip()
                    if visible
                    else "Existing lead (assigned to another team member)"
                ),
                phone_last4=digits[-4:] if digits else None,
                match=c.match,  # type: ignore[arg-type]
                score=c.score,
                owner_name=(
                    names.get(c.contact.owner_id) if visible else None
                ),
                stage=c.contact.stage if visible else None,
            )
        )
    return out
