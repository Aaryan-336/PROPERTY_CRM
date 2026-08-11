from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select

from app.deps import (
    PageDep,
    PrincipalDep,
    ScopedDep,
    SessionDep,
    rate_limit_lists,
    require,
)
from app.db import SCOPE_MARKER
from app.errors import not_found
from app.listing_normalize import canonical_token
from app.models import Contact, Property, PropertyInterest, PropertySource
from app.schemas import (
    Paged,
    PropertyCreate,
    PropertyMatch,
    PropertyOut,
    PropertyUpdate,
)
from app.serializers import user_names

router = APIRouter(tags=["properties"])


def _sighting_counts(db: SessionDep, rows: list[Property]) -> dict[int, int]:
    """How many times each listing has been seen across monitored groups.

    Only WhatsApp-sourced rows can have sightings, so manual inventory skips
    the query entirely.
    """
    ids = [p.id for p in rows if p.source == "whatsapp_group"]
    if not ids:
        return {}
    counts = db.execute(
        select(PropertySource.property_id, func.count())
        .where(PropertySource.property_id.in_(ids))
        .group_by(PropertySource.property_id)
        .execution_options(**{SCOPE_MARKER: True})
    ).all()
    return {pid: count for pid, count in counts}


def _serialize(
    db: SessionDep, rows: list[Property], counts: dict[int, int] | None = None
) -> list[PropertyOut]:
    names = user_names(db, [p.posted_by_agent_id for p in rows])
    sightings = _sighting_counts(db, rows)
    out = []
    for p in rows:
        item = PropertyOut.model_validate(p)
        item.posted_by_name = (
            names.get(p.posted_by_agent_id) if p.posted_by_agent_id else None
        )
        if p.source == "whatsapp_group":
            item.sighting_count = sightings.get(p.id, 1)
        if counts is not None:
            item.showing_count = counts.get(p.id, 0)
        out.append(item)
    return out


@router.get(
    "/properties",
    response_model=Paged[PropertyOut],
    dependencies=[Depends(rate_limit_lists), Depends(require("properties.read"))],
)
def list_properties(
    scoped: ScopedDep,
    db: SessionDep,
    page: PageDep,
    request: Request,
    location: str | None = None,
    building: str | None = None,
    listing_type: str | None = Query(default=None, pattern="^(rent|outright)$"),
    property_type: str | None = None,
    status: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    bhk: int | None = None,
    source: str | None = Query(default=None, pattern="^(manual|whatsapp_group)$"),
    review_state: str | None = None,
    q: str | None = None,
) -> Paged[PropertyOut]:
    """Inventory search. Every role may read inventory (permission matrix)."""
    stmt = scoped.properties()

    if location:
        stmt = stmt.where(Property.location.ilike(f"%{location.strip()}%"))
    if building:
        stmt = stmt.where(Property.building.ilike(f"%{building.strip()}%"))
    if listing_type:
        stmt = stmt.where(Property.listing_type == listing_type)
    if property_type:
        stmt = stmt.where(Property.property_type == property_type)
    if status:
        stmt = stmt.where(Property.status == status)
    if bhk is not None:
        stmt = stmt.where(Property.bhk == bhk)
    if source:
        stmt = stmt.where(Property.source == source)
    if review_state:
        stmt = stmt.where(Property.review_state == review_state)
    if min_price is not None:
        stmt = stmt.where(Property.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Property.price <= max_price)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Property.title.ilike(needle),
                Property.location.ilike(needle),
                Property.building.ilike(needle),
            )
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Property.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    request.state.audit.add(returned_count=len(rows), total_in_scope=total)

    return Paged[PropertyOut](
        items=_serialize(db, list(rows)),
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )


@router.post(
    "/properties",
    response_model=PropertyOut,
    status_code=201,
    dependencies=[Depends(require("properties.write"))],
)
def create_property(
    payload: PropertyCreate,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> PropertyOut:
    prop = Property(
        **payload.model_dump(exclude_unset=True),
        source="manual",
        posted_by_agent_id=principal.id,
    )
    db.add(prop)
    db.commit()
    request.state.audit.set_resource(prop.id)
    request.state.audit.add(location=prop.location, listing_type=prop.listing_type)
    return _serialize(db, [prop])[0]


@router.get("/contacts/{contact_id}/matches", response_model=list[PropertyMatch])
def contact_matches(
    contact_id: int,
    scoped: ScopedDep,
    db: SessionDep,
    limit: int = Query(default=12, ge=1, le=50),
) -> list[PropertyMatch]:
    """Inventory matching a lead's stated budget and locality preferences.

    FEATURE_LIST P2 ("suggest inventory matching a client's stated budget/
    location") and one of the PRD's core agent stories: "I want the system to
    suggest matching properties for a client's budget/location, so I don't
    manually cross-reference listings."

    Scoring is deliberately transparent rather than clever -- each result
    carries the reasons it matched, because an agent who cannot see why a flat
    was suggested will not trust the list enough to use it. Budget is a hard
    filter (with headroom); everything else contributes score.

    Both queries are role-scoped: the contact must be one the caller may see,
    and inventory is firm-wide by the permission matrix.
    """
    contact = db.execute(
        scoped.contacts().where(Contact.id == contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise not_found("Contact")

    stmt = scoped.properties().where(Property.status == "available")

    # Rejected extractions never appear in a client-facing suggestion.
    stmt = stmt.where(
        or_(Property.review_state.is_(None), Property.review_state != "rejected")
    )

    if contact.property_type_interest:
        stmt = stmt.where(
            or_(
                Property.property_type == contact.property_type_interest,
                Property.property_type.is_(None),
            )
        )

    # Budget with 10% headroom on the top end: a lead at ₹1Cr will look at
    # ₹1.1Cr, and excluding those makes the feature feel broken.
    if contact.budget_max:
        stmt = stmt.where(
            or_(
                Property.price.is_(None),
                Property.price <= contact.budget_max * Decimal("1.10"),
            )
        )
    if contact.budget_min:
        stmt = stmt.where(
            or_(
                Property.price.is_(None),
                Property.price >= contact.budget_min * Decimal("0.85"),
            )
        )

    rows = list(
        db.execute(stmt.order_by(Property.created_at.desc()).limit(200))
        .scalars()
        .all()
    )

    wanted = [
        canonical_token(loc) for loc in (contact.preferred_locations or []) if loc
    ]

    scored: list[tuple[float, list[str], Property]] = []
    for prop in rows:
        score = 0.0
        reasons: list[str] = []

        if wanted:
            haystack = canonical_token(
                f"{prop.location or ''} {prop.building or ''}"
            )
            if any(token and token in haystack for token in wanted):
                score += 0.45
                reasons.append("Preferred location")
        else:
            # No stated preference: location cannot count for or against.
            score += 0.15

        if prop.price and contact.budget_max:
            if prop.price <= contact.budget_max:
                score += 0.3
                reasons.append("Within budget")
            else:
                score += 0.12
                reasons.append("Slightly over budget")
        elif prop.price is None:
            reasons.append("Price not listed")

        if contact.property_type_interest and prop.property_type == contact.property_type_interest:
            score += 0.15
            reasons.append(f"{prop.property_type.title()} as requested")

        # Freshness: a listing seen in the last week is far more likely to
        # still be available than one nobody has mentioned in a month.
        recent = prop.last_seen_at or prop.created_at
        if recent and (datetime.now(timezone.utc) - recent) <= timedelta(days=7):
            score += 0.10
            reasons.append("Recently listed")

        if score > 0:
            scored.append((score, reasons, prop))

    scored.sort(key=lambda row: row[0], reverse=True)
    top = scored[:limit]

    serialized = _serialize(db, [p for _, _, p in top])
    return [
        PropertyMatch(
            property=item,
            score=round(min(score, 1.0), 3),
            reasons=reasons,
        )
        for (score, reasons, _), item in zip(top, serialized)
    ]


@router.get(
    "/properties/{property_id}",
    response_model=PropertyOut,
    dependencies=[Depends(require("properties.read"))],
)
def get_property(property_id: int, scoped: ScopedDep, db: SessionDep) -> PropertyOut:
    prop = db.execute(
        scoped.properties().where(Property.id == property_id)
    ).scalar_one_or_none()
    if prop is None:
        raise not_found("Property")

    # Showing count is computed from the caller's own scope, so an Agent sees
    # how many times *they* showed it, and the Owner sees the firm-wide total.
    count = db.execute(
        select(func.count()).select_from(
            scoped.property_interests()
            .where(PropertyInterest.property_id == property_id)
            .subquery()
        )
    ).scalar_one()
    return _serialize(db, [prop], {property_id: count})[0]


@router.patch(
    "/properties/{property_id}",
    response_model=PropertyOut,
    dependencies=[Depends(require("properties.write"))],
)
def update_property(
    property_id: int,
    payload: PropertyUpdate,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> PropertyOut:
    prop = db.execute(
        scoped.properties().where(Property.id == property_id)
    ).scalar_one_or_none()
    if prop is None:
        raise not_found("Property")

    fields = payload.model_dump(exclude_unset=True)
    before = {k: getattr(prop, k) for k in fields}
    for key, value in fields.items():
        setattr(prop, key, value)
    db.commit()

    request.state.audit.record_changes(before, fields)
    return _serialize(db, [prop])[0]


@router.delete(
    "/properties/{property_id}",
    status_code=204,
    response_model=None,
    dependencies=[Depends(require("properties.write"))],
)
def delete_property(
    property_id: int, scoped: ScopedDep, db: SessionDep, request: Request
) -> None:
    prop = db.execute(
        scoped.properties().where(Property.id == property_id)
    ).scalar_one_or_none()
    if prop is None:
        raise not_found("Property")
    prop.deleted_at = datetime.now(timezone.utc)
    db.commit()
    request.state.audit.add(soft_deleted=True)
