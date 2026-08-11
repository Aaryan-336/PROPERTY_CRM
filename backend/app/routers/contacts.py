from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from app.dedup import find_duplicates, to_response
from app.deps import (
    PageDep,
    PrincipalDep,
    ScopedDep,
    SessionDep,
    rate_limit_lists,
    require,
)
from app.errors import ApiError, bad_request, not_found
from app.models import Activity, Contact, User
from app.rbac import assert_capability, assert_contact_fields_writable
from app.schemas import (
    ContactCreate,
    ContactOut,
    ContactUpdate,
    Paged,
    ReassignRequest,
)
from app.serializers import serialize_contact, serialize_contacts

router = APIRouter(tags=["contacts"])


@router.get(
    "/contacts",
    response_model=Paged[ContactOut],
    dependencies=[Depends(rate_limit_lists)],
)
def list_contacts(
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    stage: str | None = None,
    owner_id: int | None = None,
    source: str | None = None,
    min_score: int | None = None,
    q: str | None = Query(default=None, description="Name or phone fragment"),
) -> Paged[ContactOut]:
    """List contacts the caller is permitted to see.

    ``scoped.contacts()`` already carries ``WHERE owner_id = :me`` for Agent and
    Cold Caller. The filters below narrow that set further and can never widen
    it -- passing ``owner_id`` for a colleague yields an empty page, not theirs.
    """
    stmt = scoped.contacts()

    if stage:
        stmt = stmt.where(Contact.stage == stage)
    if owner_id is not None:
        stmt = stmt.where(Contact.owner_id == owner_id)
    if source:
        stmt = stmt.where(Contact.lead_source == source)
    if min_score is not None:
        stmt = stmt.where(Contact.lead_score >= min_score)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Contact.first_name.ilike(needle),
                Contact.last_name.ilike(needle),
                Contact.phone.ilike(needle),
            )
        )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    rows = (
        db.execute(
            stmt.order_by(Contact.updated_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )

    request.state.audit.add(returned_count=len(rows), total_in_scope=total)

    return Paged[ContactOut](
        items=serialize_contacts(db, principal, rows),
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )


@router.post("/contacts", response_model=ContactOut, status_code=201)
def create_contact(
    payload: ContactCreate,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
    force: bool = Query(
        default=False,
        description="Create even though duplicate candidates were found.",
    ),
) -> ContactOut:
    assert_capability(principal, "contacts.create")

    candidates = find_duplicates(
        db, payload.first_name, payload.last_name, payload.phone
    )
    if candidates and not force:
        raise ApiError(
            409,
            "duplicate_candidates",
            "This looks like a lead already in the system. "
            "Review the matches, then resend with force=true to create anyway.",
            {
                "candidates": [
                    c.model_dump(mode="json")
                    for c in to_response(db, principal, candidates)
                ]
            },
        )

    # An Agent or Cold Caller always creates leads under their own name; only
    # the Owner may hand a new lead directly to someone else.
    owner_id = principal.id
    if payload.owner_id is not None and payload.owner_id != principal.id:
        assert_capability(principal, "contacts.reassign")
        owner_id = payload.owner_id

    data = payload.model_dump(exclude={"owner_id"}, exclude_unset=True)
    contact = Contact(
        **data,
        owner_id=owner_id,
        # SECURITY_MODEL.md: new leads start masked for staff, so a lead list
        # grabbed before any real work is done on it carries no usable numbers.
        phone_masked=not principal.sees_everything,
        stage=payload.stage or "new",
    )
    db.add(contact)
    db.commit()

    request.state.audit.set_resource(contact.id)
    request.state.audit.add(
        created_owner_id=owner_id,
        forced_over_duplicates=bool(candidates and force),
        duplicate_candidate_ids=[c.contact.id for c in candidates] if candidates else [],
    )
    return serialize_contact(db, principal, contact)


@router.get("/contacts/export", dependencies=[Depends(require("contacts.export"))])
def export_contacts(
    scoped: ScopedDep, db: SessionDep, request: Request
) -> StreamingResponse:
    """Bulk CSV export. Owner only, and always audited with a row count.

    Agent and Cold Caller are refused by the capability dependency before any
    query runs -- SECURITY_MODEL.md §2 asks for the capability to be absent from
    the role, not merely hidden from their UI.
    """
    rows = db.execute(scoped.contacts().order_by(Contact.id)).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "stage",
            "lead_source",
            "budget_min",
            "budget_max",
            "preferred_locations",
            "owner_id",
            "created_at",
        ]
    )
    for c in rows:
        writer.writerow(
            [
                c.id,
                c.first_name,
                c.last_name or "",
                c.email or "",
                c.phone or "",
                c.stage or "",
                c.lead_source or "",
                c.budget_min or "",
                c.budget_max or "",
                "|".join(c.preferred_locations or []),
                c.owner_id or "",
                c.created_at.isoformat() if c.created_at else "",
            ]
        )

    request.state.audit.add(exported_count=len(rows), format="csv")

    filename = f"contacts-{datetime.now(timezone.utc):%Y%m%d-%H%M}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/contacts/bulk-import",
    dependencies=[Depends(require("contacts.bulk_import"))],
)
def bulk_import_contacts(
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
    file: UploadFile = File(description="CSV with a first_name column"),
    assign_to: int | None = Query(
        default=None, description="Staff member to assign every imported row to."
    ),
) -> dict:
    """CSV import, Owner only. Rows that duplicate an existing lead are skipped.

    Import is the mirror image of export and gets the same treatment: gated by
    capability, and audited with counts.
    """
    raw = file.file.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))

    imported = 0
    skipped: list[dict] = []
    allowed = {
        "first_name",
        "last_name",
        "email",
        "phone",
        "lead_source",
        "campaign",
        "property_type_interest",
        "buyer_type",
        "stage",
    }

    for index, row in enumerate(reader, start=2):
        clean = {k: (v or "").strip() for k, v in row.items() if k in allowed}
        if not clean.get("first_name"):
            skipped.append({"row": index, "reason": "missing first_name"})
            continue

        dupes = find_duplicates(
            db, clean["first_name"], clean.get("last_name"), clean.get("phone")
        )
        if dupes:
            skipped.append({"row": index, "reason": "duplicate", "matched": dupes[0].contact.id})
            continue

        budget_min = _to_decimal(row.get("budget_min"))
        budget_max = _to_decimal(row.get("budget_max"))
        locations = [
            part.strip()
            for part in (row.get("preferred_locations") or "").split("|")
            if part.strip()
        ]

        db.add(
            Contact(
                **{k: (v or None) for k, v in clean.items()},
                budget_min=budget_min,
                budget_max=budget_max,
                preferred_locations=locations or None,
                owner_id=assign_to or principal.id,
                phone_masked=False,
                stage=clean.get("stage") or "new",
            )
        )
        imported += 1

    db.commit()
    request.state.audit.add(
        imported_count=imported,
        skipped_count=len(skipped),
        assigned_to=assign_to or principal.id,
        filename=file.filename,
    )
    return {"imported": imported, "skipped": skipped}


def _to_decimal(value: str | None) -> Decimal | None:
    if not value or not value.strip():
        return None
    try:
        return Decimal(value.strip().replace(",", ""))
    except InvalidOperation:
        return None


@router.get("/contacts/{contact_id}", response_model=ContactOut)
def get_contact(
    contact_id: int, scoped: ScopedDep, db: SessionDep, principal: PrincipalDep
) -> ContactOut:
    contact = db.execute(
        scoped.contacts().where(Contact.id == contact_id)
    ).scalar_one_or_none()
    if contact is None:
        # Same 404 whether the row is absent or out of scope, so ids cannot be
        # probed to map another agent's book.
        raise not_found("Contact")
    return serialize_contact(db, principal, contact)


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> ContactOut:
    assert_capability(principal, "contacts.edit")

    contact = db.execute(
        scoped.contacts().where(Contact.id == contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise not_found("Contact")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return serialize_contact(db, principal, contact)

    assert_contact_fields_writable(principal, set(fields))

    before = {k: getattr(contact, k) for k in fields}
    previous_stage = contact.stage

    for key, value in fields.items():
        setattr(contact, key, value)
    contact.updated_at = datetime.now(timezone.utc)

    # A stage change is a visible event in its own right, not just a column
    # edit -- it belongs on the lead's Journey Timeline and the owner's feed.
    if "stage" in fields and fields["stage"] != previous_stage:
        db.add(
            Activity(
                contact_id=contact.id,
                user_id=principal.id,
                type="stage_change",
                body=f"Stage moved from {previous_stage or 'new'} to {fields['stage']}",
            )
        )

    db.commit()
    request.state.audit.record_changes(before, fields)
    return serialize_contact(db, principal, contact)


@router.delete(
    "/contacts/{contact_id}",
    status_code=204,
    response_model=None,
    dependencies=[Depends(require("contacts.delete"))],
)
def delete_contact(
    contact_id: int, scoped: ScopedDep, db: SessionDep, request: Request
) -> None:
    """Soft delete only. The row and its audit history survive."""
    contact = db.execute(
        scoped.contacts().where(Contact.id == contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise not_found("Contact")
    contact.deleted_at = datetime.now(timezone.utc)
    db.commit()
    request.state.audit.add(soft_deleted=True, contact_name=contact.full_name)


@router.post(
    "/contacts/{contact_id}/reassign",
    response_model=ContactOut,
    dependencies=[Depends(require("contacts.reassign"))],
)
def reassign_contact(
    contact_id: int,
    payload: ReassignRequest,
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> ContactOut:
    contact = db.execute(
        scoped.contacts().where(Contact.id == contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise not_found("Contact")

    new_owner = db.execute(
        scoped.users().where(User.id == payload.new_owner_id)
    ).scalar_one_or_none()
    if new_owner is None:
        raise bad_request("unknown_user", "That staff member does not exist.")

    old_owner_id = contact.owner_id
    contact.owner_id = new_owner.id
    contact.updated_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            contact_id=contact.id,
            user_id=principal.id,
            type="note",
            body=f"Reassigned to {new_owner.name}"
            + (f" — {payload.reason}" if payload.reason else ""),
        )
    )
    db.commit()

    # SECURITY_MODEL.md requires old and new owner on the audit entry.
    request.state.audit.add(
        old_owner_id=old_owner_id,
        new_owner_id=new_owner.id,
        reason=payload.reason,
    )
    return serialize_contact(db, principal, contact)
