"""Property interests -- the "who showed what to whom" record.

FEATURE_LIST calls this "the backbone of owner visibility". Each showing is its
own immutable row: the same agent may show the same property to the same client
twice, and both events matter.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from app.deps import (
    PageDep,
    PrincipalDep,
    ScopedDep,
    SessionDep,
    rate_limit_lists,
    require,
)
from app.errors import bad_request, not_found
from app.models import Activity, Contact, Property, PropertyInterest
from app.schemas import Paged, PropertyInterestCreate, PropertyInterestOut
from app.serializers import user_names

router = APIRouter(tags=["showings"])

# An interest level that means the client physically saw the property, which is
# also what unlocks a masked phone number for the agent who logged it.
VISIT_LEVELS = {"site_visit_done", "negotiating"}

STAGE_FOR_LEVEL = {
    "inquired": "contacted",
    "site_visit_scheduled": "site_visit_scheduled",
    "site_visit_done": "visited",
    "negotiating": "negotiating",
}


@router.post(
    "/property-interests",
    response_model=PropertyInterestOut,
    status_code=201,
    dependencies=[Depends(require("property_interests.write"))],
)
def log_showing(
    payload: PropertyInterestCreate,
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> PropertyInterestOut:
    """Log that a property was shown to a client.

    ``shown_by_agent_id`` comes from the auth context and is never accepted from
    the client (API_SPEC.md) -- an agent cannot attribute a showing to someone
    else, which is what makes the owner's timeline trustworthy.
    """
    contact = db.execute(
        scoped.contacts().where(Contact.id == payload.contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise not_found("Contact")

    prop = db.execute(
        scoped.properties().where(Property.id == payload.property_id)
    ).scalar_one_or_none()
    if prop is None:
        raise not_found("Property")

    shown_at = payload.shown_at or datetime.now(timezone.utc)
    interest = PropertyInterest(
        contact_id=contact.id,
        property_id=prop.id,
        shown_by_agent_id=principal.id,
        interest_level=payload.interest_level,
        shown_at=shown_at,
    )
    db.add(interest)

    # The showing is also an activity, so it lands on the lead's Journey
    # Timeline and the owner's live feed without a second write from the client.
    label = prop.title or f"{prop.building or prop.property_type or 'Property'}"
    db.add(
        Activity(
            contact_id=contact.id,
            property_id=prop.id,
            user_id=principal.id,
            type="site_visit"
            if payload.interest_level in VISIT_LEVELS
            else "note",
            body=payload.note
            or f"{payload.interest_level.replace('_', ' ').title()} — {label}, {prop.location}",
            occurred_at=shown_at,
        )
    )

    new_stage = STAGE_FOR_LEVEL.get(payload.interest_level)
    if new_stage and contact.stage != new_stage:
        previous = contact.stage
        contact.stage = new_stage
        contact.updated_at = datetime.now(timezone.utc)
        db.add(
            Activity(
                contact_id=contact.id,
                user_id=principal.id,
                type="stage_change",
                body=f"Stage moved from {previous or 'new'} to {new_stage}",
            )
        )

    db.commit()

    request.state.audit.set_resource(prop.id)
    request.state.audit.add(
        contact_id=contact.id,
        property_id=prop.id,
        interest_level=payload.interest_level,
        shown_by=principal.id,
    )

    names = user_names(db, [principal.id])
    return PropertyInterestOut(
        contact_id=contact.id,
        contact_name=contact.full_name,
        property_id=prop.id,
        property_title=prop.title,
        property_location=prop.location,
        shown_by_agent_id=principal.id,
        shown_by_name=names.get(principal.id),
        interest_level=payload.interest_level,
        shown_at=shown_at,
    )


@router.get(
    "/property-interests",
    response_model=Paged[PropertyInterestOut],
    dependencies=[
        Depends(require("property_interests.read")),
        Depends(rate_limit_lists),
    ],
)
def list_showings(
    scoped: ScopedDep,
    db: SessionDep,
    page: PageDep,
    request: Request,
    contact_id: int | None = None,
    property_id: int | None = None,
    agent_id: int | None = None,
) -> Paged[PropertyInterestOut]:
    """Filterable by contact, property or agent -- the three axes API_SPEC lists.

    For an Agent the underlying statement is already restricted to showings they
    performed, so ``agent_id=<someone else>`` returns nothing rather than
    another agent's record of who they showed what to.
    """
    stmt = scoped.property_interests()
    if contact_id is not None:
        stmt = stmt.where(PropertyInterest.contact_id == contact_id)
    if property_id is not None:
        stmt = stmt.where(PropertyInterest.property_id == property_id)
    if agent_id is not None:
        stmt = stmt.where(PropertyInterest.shown_by_agent_id == agent_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(PropertyInterest.shown_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )

    contact_ids = {r.contact_id for r in rows}
    property_ids = {r.property_id for r in rows}

    contacts = (
        {
            c.id: c
            for c in db.execute(
                scoped.contacts().where(Contact.id.in_(contact_ids))
            ).scalars()
        }
        if contact_ids
        else {}
    )
    props = (
        {
            p.id: p
            for p in db.execute(
                scoped.properties().where(Property.id.in_(property_ids))
            ).scalars()
        }
        if property_ids
        else {}
    )
    names = user_names(db, [r.shown_by_agent_id for r in rows])

    request.state.audit.add(returned_count=len(rows), total_in_scope=total)

    items = []
    for r in rows:
        contact = contacts.get(r.contact_id)
        prop = props.get(r.property_id)
        items.append(
            PropertyInterestOut(
                contact_id=r.contact_id,
                contact_name=contact.full_name if contact else None,
                property_id=r.property_id,
                property_title=prop.title if prop else None,
                property_location=prop.location if prop else None,
                shown_by_agent_id=r.shown_by_agent_id,
                shown_by_name=names.get(r.shown_by_agent_id),
                interest_level=r.interest_level,
                shown_at=r.shown_at,
            )
        )

    return Paged[PropertyInterestOut](
        items=items,
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )
