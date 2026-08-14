from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from app.db import system_scope
from app.dedup import find_duplicates, to_response
from app.lead_import import distribute, parse_lead_file
from app.deps import (
    PageDep,
    PrincipalDep,
    ScopedDep,
    SessionDep,
    rate_limit_lists,
    require,
)
from app.errors import ApiError, bad_request, not_found
from app.models import (
    Activity,
    Contact,
    ContactAssignment,
    LeadBatch,
    Task,
    User,
)
from app.rbac import assert_capability, assert_contact_fields_writable
from app.schemas import (
    AssignRequest,
    AssignResponse,
    Assignee,
    ImportAssignment,
    ImportPreview,
    ImportResult,
    ImportRowPreview,
    ContactCreate,
    ContactOut,
    ContactUpdate,
    Paged,
    ReassignRequest,
)
from app.push import send_to_users
from app.serializers import serialize_contact, serialize_contacts

router = APIRouter(tags=["contacts"])


@router.get(
    "/contacts",
    response_model=Paged[ContactOut],
    dependencies=[Depends(rate_limit_lists), Depends(require("contacts.browse"))],
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
    batch_id: int | None = Query(
        default=None, description="Only numbers from this imported database"
    ),
    include_targets: bool = Query(
        default=False,
        description=(
            "Include imported numbers nobody has flagged as a lead yet. "
            "Off by default — this endpoint backs the leads screen."
        ),
    ),
) -> Paged[ContactOut]:
    """List contacts the caller is permitted to see.

    ``scoped.contacts()`` already carries ``WHERE owner_id = :me`` for Agent and
    Cold Caller. The filters below narrow that set further and can never widen
    it -- passing ``owner_id`` for a colleague yields an empty page, not theirs.

    Unflagged imported numbers are excluded unless asked for. Six hundred rows
    off a bought spreadsheet are not six hundred leads, and letting them into
    this list buries the handful of people who actually want to buy something.
    They remain fully visible in the call queue, which is where they belong.
    """
    stmt = scoped.contacts()

    if not include_targets:
        stmt = stmt.where(Contact.is_lead.is_(True))
    if batch_id is not None:
        stmt = stmt.where(Contact.batch_id == batch_id)
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
    "/contacts/bulk-import/preview",
    response_model=ImportPreview,
    dependencies=[Depends(require("contacts.bulk_import"))],
)
def preview_import(
    db: SessionDep,
    request: Request,
    file: UploadFile = File(description="Excel (.xlsx) or CSV calling list"),
) -> ImportPreview:
    """Parse a spreadsheet and report what would happen, writing nothing.

    Separate from the commit because these files have no agreed shape — a
    portal export, a purchased list, something typed by hand. The owner should
    see which column was read as the phone number, and how many rows are
    already in the system, before any of it lands in a caller's queue.
    """
    raw = file.file.read()
    try:
        parsed = parse_lead_file(raw, file.filename or "")
    except ValueError as exc:
        raise bad_request("unreadable_file", str(exc)) from exc

    sample: list[ImportRowPreview] = []
    duplicates = 0
    invalid = 0

    for row in parsed.rows:
        if not row.usable:
            invalid += 1
            status, detail = "invalid", row.problem
        else:
            # Checked against the whole contact table, not the caller's scope:
            # re-importing a lead that already belongs to a colleague is how
            # ownership gets quietly rewritten (see app/dedup.py).
            existing = find_duplicates(
                db, row.first_name, row.last_name, row.phone
            )
            if existing:
                duplicates += 1
                status, detail = "duplicate", "already in the system"
            else:
                status, detail = "new", None

        if len(sample) < 25:
            sample.append(
                ImportRowPreview(
                    row_number=row.row_number,
                    name=row.display_name or "—",
                    phone=row.phone or "—",
                    email=row.email or None,
                    location=row.location or None,
                    status=status,
                    detail=detail,
                )
            )

    importable = parsed.total_rows - duplicates - invalid
    request.state.audit.add(
        previewed=True,
        filename=file.filename,
        total_rows=parsed.total_rows,
        importable=importable,
    )

    return ImportPreview(
        filename=file.filename or "upload",
        sheet_name=parsed.sheet_name,
        header_row=parsed.header_row,
        detected_columns=parsed.detected_columns,
        total_rows=parsed.total_rows,
        importable=importable,
        duplicates=duplicates,
        invalid=invalid,
        warnings=parsed.warnings,
        sample=sample,
    )


@router.post(
    "/contacts/bulk-import",
    response_model=ImportResult,
    dependencies=[Depends(require("contacts.bulk_import"))],
)
def bulk_import_contacts(
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
    file: UploadFile = File(description="Excel (.xlsx) or CSV calling list"),
    assign_to: list[int] = Form(
        default=[],
        description=(
            "Staff who receive the numbers. Several ids deal the rows out "
            "round-robin. Empty assigns them to the importing Owner."
        ),
    ),
    name: str = Form(
        default="",
        description="What to call this database. Defaults to the filename.",
    ),
) -> ImportResult:
    """Import a calling list as call targets and assign it.

    Assignment is the whole point: setting `owner_id` is what puts a number into
    that person's call queue, since `/call-queue` is scoped to the contacts a
    caller owns. There is no separate queue table to populate.

    What lands here is *not* a lead. A purchased spreadsheet is a list of people
    who have not asked to hear from us, and treating those as leads inflates
    every pipeline figure the owner looks at. They import with `is_lead=False`,
    which keeps them out of the leads screen while leaving them fully callable;
    a caller flags the ones worth keeping (see `marked_lead` in routers/calls).

    Every row is tagged with a batch so the owner can compare one list against
    another later — that is the whole basis of `GET /lead-batches`.

    Owner only, and audited with counts and the recipients — a bulk write of
    other people's contact details is exactly the kind of movement the audit
    log exists to record.
    """
    raw = file.file.read()
    try:
        parsed = parse_lead_file(raw, file.filename or "")
    except ValueError as exc:
        raise bad_request("unreadable_file", str(exc)) from exc

    targets = _resolve_assignees(db, assign_to, principal)
    usable = parsed.usable_rows

    duplicates = 0
    invalid = sum(1 for r in parsed.rows if not r.usable)
    fresh: list = []
    for row in usable:
        if find_duplicates(db, row.first_name, row.last_name, row.phone):
            duplicates += 1
            continue
        fresh.append(row)

    # Recorded before the rows so the counts describe the file as delivered,
    # not what survived it. "600 rows in, 480 usable" is exactly the comparison
    # that tells the owner one vendor's list is dirtier than another's, and it
    # is unrecoverable once the duplicates have been dropped.
    batch = LeadBatch(
        name=(name.strip() or file.filename or "Untitled list")[:120],
        source_filename=file.filename,
        uploaded_by_id=principal.id,
        total_rows=parsed.total_rows,
        imported_rows=len(fresh),
        duplicate_rows=duplicates,
        invalid_rows=invalid,
    )
    db.add(batch)
    db.flush()

    buckets = distribute(fresh, len(targets))
    counts: dict[int, int] = {}

    for target, rows in zip(targets, buckets):
        for row in rows:
            db.add(
                Contact(
                    first_name=row.first_name or "Unknown",
                    last_name=row.last_name or None,
                    phone=row.phone or None,
                    email=row.email or None,
                    preferred_locations=[row.location] if row.location else None,
                    lead_source=row.source or "imported_list",
                    owner_id=target.id,
                    stage="new",
                    batch_id=batch.id,
                    # A number off a bought list, not a lead. It is callable
                    # immediately but stays out of the pipeline until a caller
                    # has spoken to the person and flagged them.
                    is_lead=False,
                    # A cold-calling list is unusable if the caller cannot see
                    # the number, so imported rows are not masked. The number
                    # still only appears in the queue of whoever it was
                    # assigned to.
                    phone_masked=False,
                )
            )
            counts[target.id] = counts.get(target.id, 0) + 1
    db.commit()

    imported = sum(counts.values())
    request.state.audit.add(
        batch_id=batch.id,
        batch_name=batch.name,
        imported_count=imported,
        duplicate_count=duplicates,
        invalid_count=invalid,
        filename=file.filename,
        assigned_to=[t.id for t in targets],
    )

    return ImportResult(
        batch_id=batch.id,
        batch_name=batch.name,
        imported=imported,
        duplicates=duplicates,
        invalid=invalid,
        assignments=[
            ImportAssignment(
                user_id=t.id, name=t.name, assigned=counts.get(t.id, 0)
            )
            for t in targets
        ],
    )


def _resolve_assignees(
    db: SessionDep, ids: list[int], principal
) -> list[User]:
    """Validate the requested recipients, defaulting to the importer."""
    wanted = [i for i in dict.fromkeys(ids) if i]
    if not wanted:
        with system_scope():
            return [db.get(User, principal.id)]

    with system_scope():
        found = (
            db.execute(
                select(User)
                .where(User.id.in_(wanted))
                .where(User.deleted_at.is_(None))
            )
            .scalars()
            .all()
        )
    if len(found) != len(wanted):
        missing = set(wanted) - {u.id for u in found}
        raise bad_request(
            "unknown_user",
            f"No active staff member with id {sorted(missing)}.",
        )

    # Return them in the order the caller asked for. `IN (...)` gives no
    # ordering guarantee, and with an uneven split that would make *who* gets
    # the extra rows differ between identical imports.
    by_id = {u.id: u for u in found}
    return [by_id[i] for i in wanted]


def _to_decimal(value: str | None) -> Decimal | None:
    if not value or not value.strip():
        return None
    try:
        return Decimal(value.strip().replace(",", ""))
    except InvalidOperation:
        return None


@router.get(
    "/contacts/{contact_id}",
    response_model=ContactOut,
    dependencies=[Depends(require("contacts.browse"))],
)
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


@router.get("/contacts/{contact_id}/assignees", response_model=list[Assignee])
def list_assignees(
    contact_id: int, scoped: ScopedDep, db: SessionDep
) -> list[Assignee]:
    """Who else is working this lead.

    Scoped like any other read: you can only ask about a contact you can
    already see, so this cannot be used to enumerate the firm's staff against
    leads you have no access to.
    """
    contact = db.execute(
        scoped.contacts().where(Contact.id == contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise not_found("Contact")
    return _assignees(db, contact_id)


@router.put(
    "/contacts/{contact_id}/assignees",
    response_model=AssignResponse,
    dependencies=[Depends(require("contacts.reassign"))],
)
def set_assignees(
    contact_id: int,
    payload: AssignRequest,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> AssignResponse:
    """Put a lead in front of one or more staff members.

    PUT rather than POST because the body is the desired set, not an addition —
    the screen behind it is a list of checkboxes, and unticking someone has to
    remove them without a second request.

    Each newly assigned person gets a Task, which is what makes the assignment
    show up as work rather than as a silent permission change: the lead appears
    in their follow-ups with a due date, and nothing about this feature requires
    them to go looking for it.

    Assignment also widens what they can see — app/scoping.py treats an
    assignment as access to that contact — so this is Owner-only, under the same
    capability as reassignment.
    """
    with system_scope():
        contact = db.get(Contact, contact_id)
    if contact is None or contact.deleted_at is not None:
        raise not_found("Contact")

    wanted = [i for i in dict.fromkeys(payload.user_ids) if i]

    with system_scope():
        staff = (
            db.execute(
                select(User)
                .where(User.id.in_(wanted))
                .where(User.deleted_at.is_(None))
            )
            .scalars()
            .all()
            if wanted
            else []
        )
    if len(staff) != len(wanted):
        missing = set(wanted) - {u.id for u in staff}
        raise bad_request(
            "unknown_user", f"No active staff member with id {sorted(missing)}."
        )

    with system_scope():
        existing = {
            row.user_id: row
            for row in db.execute(
                select(ContactAssignment).where(
                    ContactAssignment.contact_id == contact_id
                )
            ).scalars()
        }

    by_id = {u.id: u for u in staff}
    to_add = [uid for uid in wanted if uid not in existing]
    to_remove = [uid for uid in existing if uid not in wanted]

    due = payload.due_at or datetime.now(timezone.utc) + timedelta(hours=24)
    tasks_created = 0

    for uid in to_add:
        db.add(
            ContactAssignment(
                contact_id=contact_id,
                user_id=uid,
                assigned_by=principal.id,
                note=payload.note,
            )
        )
        db.add(
            Task(
                contact_id=contact_id,
                assigned_to=uid,
                created_by=principal.id,
                title=f"Work {contact.full_name}"
                + (f" — {payload.note}" if payload.note else ""),
                due_at=due,
                status="pending",
            )
        )
        tasks_created += 1

    for uid in to_remove:
        db.delete(existing[uid])
        # Their open task for this lead goes too. Leaving it would show them
        # work on a contact they can no longer open, which reads as a bug.
        with system_scope():
            orphaned = (
                db.execute(
                    select(Task)
                    .where(Task.contact_id == contact_id)
                    .where(Task.assigned_to == uid)
                    .where(Task.status == "pending")
                )
                .scalars()
                .all()
            )
        for task in orphaned:
            task.status = "cancelled"

    db.commit()

    request.state.audit.set_resource(contact_id)
    request.state.audit.add(
        assigned=to_add,
        unassigned=to_remove,
        tasks_created=tasks_created,
    )

    if to_add:
        send_to_users(
            db,
            to_add,
            title="Lead assigned to you",
            body=f"{principal.name} assigned you {contact.full_name}"
            + (f" — {payload.note}" if payload.note else ""),
            url=f"/contacts/{contact_id}",
            tag="assignment",
        )

    names = {u.id: u.name for u in staff}
    return AssignResponse(
        contact_id=contact_id,
        assignees=_assignees(db, contact_id),
        added=[names[uid] for uid in to_add],
        removed=[_name_of(db, uid) for uid in to_remove],
        tasks_created=tasks_created,
    )


def _name_of(db: SessionDep, user_id: int) -> str:
    with system_scope():
        user = db.get(User, user_id)
    return user.name if user else str(user_id)


def _assignees(db: SessionDep, contact_id: int) -> list[Assignee]:
    """Current assignees, newest first, with who put them there."""
    assigner = aliased(User)
    with system_scope():
        rows = db.execute(
            select(ContactAssignment, User, assigner)
            .join(User, User.id == ContactAssignment.user_id)
            .outerjoin(assigner, assigner.id == ContactAssignment.assigned_by)
            .where(ContactAssignment.contact_id == contact_id)
            .order_by(ContactAssignment.created_at.desc())
        ).all()
    return [
        Assignee(
            user_id=a.user_id,
            name=u.name,
            role=u.role,
            assigned_by_name=by.name if by else None,
            created_at=a.created_at,
            note=a.note,
        )
        for a, u, by in rows
    ]
