"""Per-database performance for uploaded calling lists.

The owner buys lists. The only question worth asking afterwards is whether a
given list produced anything, and lists differ enormously — a builder's own
enquiry export converts an order of magnitude better than a scraped directory,
and the only way to know which is which is to keep the rows grouped and compare.

Owner-scoped throughout. A cold caller has no business seeing that the list
they are working converts at 2%, and an agent has no business seeing the shape
of the firm's lead sourcing at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.db import system_scope
from app.deps import SessionDep, rate_limit_lists, require
from app.errors import not_found
from app.models import CallLog, Contact, LeadBatch, PropertyInterest, User
from app.schemas import BatchPerformance

router = APIRouter(tags=["lead-batches"])

# The outcomes where a human actually picked up. A list whose numbers are dead
# fails here rather than at conversion, and the two are worth telling apart:
# one is a bad list, the other is a list being worked badly.
REACHED_OUTCOMES = ("connected", "interested", "callback_requested")


def _rate(numerator: int, denominator: int) -> float | None:
    """None, not zero, when there is nothing to divide by.

    A list uploaded an hour ago and a list that was worked hard and produced
    nothing both show 0% otherwise, and they call for opposite decisions.
    """
    return (numerator / denominator) if denominator else None


@router.get(
    "/lead-batches",
    response_model=list[BatchPerformance],
    dependencies=[
        Depends(rate_limit_lists),
        # Whoever may upload a database may see how it performed. Deliberately
        # the same capability rather than a new one — these are two halves of a
        # single owner responsibility.
        Depends(require("contacts.bulk_import")),
    ],
)
def list_batches(
    db: SessionDep,
    request: Request,
    include_archived: bool = Query(default=False),
) -> list[BatchPerformance]:
    """Every uploaded database with its live conversion numbers.

    The counts are recomputed on read rather than stored on the batch. Numbers
    get called and flagged for weeks after an import, so anything frozen at
    upload time would be wrong by the time it mattered.

    All aggregates are grouped in a handful of queries rather than one pass per
    batch, so a firm with fifty uploaded lists costs the same as one with two.
    """
    with system_scope():
        stmt = select(LeadBatch).order_by(LeadBatch.created_at.desc())
        if not include_archived:
            stmt = stmt.where(LeadBatch.archived_at.is_(None))
        batches = db.execute(stmt).scalars().all()
        if not batches:
            return []

        ids = [b.id for b in batches]
        uploader_ids = {b.uploaded_by_id for b in batches if b.uploaded_by_id}
        uploader_names = (
            {
                row[0]: row[1]
                for row in db.execute(
                    select(User.id, User.name).where(User.id.in_(uploader_ids))
                )
            }
            if uploader_ids
            else {}
        )
        stats = _aggregate(db, ids)

    request.state.audit.add(batch_count=len(batches))

    return [
        _to_schema(b, uploader_names.get(b.uploaded_by_id), stats.get(b.id, {}))
        for b in batches
    ]


@router.get(
    "/lead-batches/{batch_id}",
    response_model=BatchPerformance,
    dependencies=[Depends(require("contacts.bulk_import"))],
)
def get_batch(
    batch_id: int, db: SessionDep, request: Request
) -> BatchPerformance:
    with system_scope():
        batch = db.get(LeadBatch, batch_id)
        if batch is None:
            raise not_found("Lead batch")
        uploader = (
            db.get(User, batch.uploaded_by_id) if batch.uploaded_by_id else None
        )
        stats = _aggregate(db, [batch_id])

    request.state.audit.set_resource(batch_id)
    return _to_schema(
        batch, uploader.name if uploader else None, stats.get(batch_id, {})
    )


def _aggregate(db: SessionDep, ids: list[int]) -> dict[int, dict]:
    """Live per-batch counts, in five grouped queries regardless of batch count.

    Must be called inside ``system_scope()`` — these are firm-wide aggregates,
    and the endpoints above are already owner-gated by capability.
    """
    # Contacts still in the batch, and how many were kept as leads. A row
    # deleted after import should not count against the list that supplied it.
    rows = db.execute(
        select(
            Contact.batch_id,
            func.count(),
            func.count().filter(Contact.is_lead.is_(True)),
            func.count().filter(Contact.stage == "closed"),
        )
        .where(Contact.batch_id.in_(ids))
        .where(Contact.deleted_at.is_(None))
        .group_by(Contact.batch_id)
    ).all()
    out: dict[int, dict] = {
        r[0]: {"size": r[1], "leads": r[2], "closed": r[3]} for r in rows
    }

    # Distinct contacts touched, not calls placed — three attempts at the same
    # dead number is one number worked, and counting calls would make a list of
    # unreachable numbers look thoroughly covered.
    for batch_id, called, reached, last_at in db.execute(
        select(
            Contact.batch_id,
            func.count(func.distinct(CallLog.contact_id)),
            func.count(func.distinct(CallLog.contact_id)).filter(
                CallLog.outcome.in_(REACHED_OUTCOMES)
            ),
            func.max(CallLog.created_at),
        )
        .join(Contact, Contact.id == CallLog.contact_id)
        .where(Contact.batch_id.in_(ids))
        .where(Contact.deleted_at.is_(None))
        .group_by(Contact.batch_id)
    ):
        out.setdefault(batch_id, {}).update(
            called=called, reached=reached, last_activity_at=last_at
        )

    for batch_id, showings in db.execute(
        select(Contact.batch_id, func.count())
        .join(PropertyInterest, PropertyInterest.contact_id == Contact.id)
        .where(Contact.batch_id.in_(ids))
        .where(PropertyInterest.shown_at.is_not(None))
        .group_by(Contact.batch_id)
    ):
        out.setdefault(batch_id, {})["showings"] = showings

    # Who is actually working the list. Shown on the card because "this list
    # is converting badly" and "nobody has been given this list" look identical
    # in the numbers alone.
    for batch_id, name in db.execute(
        select(Contact.batch_id, User.name)
        .join(User, User.id == Contact.owner_id)
        .where(Contact.batch_id.in_(ids))
        .where(Contact.deleted_at.is_(None))
        .group_by(Contact.batch_id, User.name)
        .order_by(User.name)
    ):
        out.setdefault(batch_id, {}).setdefault("assigned_to", []).append(name)

    return out


def _to_schema(
    batch: LeadBatch, uploader: str | None, stats: dict
) -> BatchPerformance:
    size = stats.get("size", 0)
    called = stats.get("called", 0)
    reached = stats.get("reached", 0)
    leads = stats.get("leads", 0)

    return BatchPerformance(
        id=batch.id,
        name=batch.name,
        source_filename=batch.source_filename,
        uploaded_by=uploader,
        created_at=batch.created_at,
        archived_at=batch.archived_at,
        total_rows=batch.total_rows,
        duplicate_rows=batch.duplicate_rows,
        invalid_rows=batch.invalid_rows,
        size=size,
        called=called,
        uncalled=max(size - called, 0),
        reached=reached,
        leads=leads,
        showings=stats.get("showings", 0),
        closed=stats.get("closed", 0),
        # How much of the list has been worked at all.
        contact_rate=_rate(called, size),
        # Of the numbers worked, how many were live people.
        reach_rate=_rate(reached, called),
        # The figure that decides whether to buy from this source again:
        # leads produced per number actually called, not per row in the file.
        # Dividing by file size would punish a good list that nobody finished.
        conversion_rate=_rate(leads, called),
        assigned_to=stats.get("assigned_to", []),
        last_activity_at=stats.get("last_activity_at"),
    )
