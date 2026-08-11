"""Role-scoped query construction.

This module is the single source of truth for "what rows can this caller see".
Every read path in the API starts from a ``ScopedQuery`` method, and
``app/db.py`` refuses to execute a guarded query that did not.

The rules encode the permission matrix in ROLES_PERMISSIONS.md. Where the
matrix says a role sees nothing, the corresponding method returns a statement
with an impossible predicate rather than raising -- so a caller that forgets an
endpoint-level authorization check still gets an empty list rather than data.
Endpoint-level checks exist too (``app/rbac.py``); the two are independent
layers and either one alone would prevent a leak.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, false, select

from app.db import SCOPE_MARKER
from app.models import (
    ROLE_AGENT,
    ROLE_OWNER,
    Activity,
    AuditLog,
    CallLog,
    Contact,
    Property,
    PropertyInterest,
    PropertySource,
    Task,
    User,
    WhatsAppGroup,
    WhatsAppMessage,
)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, resolved from the JWT and the sessions table."""

    id: int
    name: str
    role: str
    manager_id: int | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == ROLE_OWNER

    @property
    def sees_everything(self) -> bool:
        """Firm-wide visibility. Owner only in Phase 1."""
        return self.role == ROLE_OWNER


def _mark(stmt: Select) -> Select:
    """Stamp a statement as having passed through role scoping."""
    return stmt.execution_options(**{SCOPE_MARKER: True})


class ScopedQuery:
    """Builds SELECTs already filtered to what ``principal`` may see."""

    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    # -- helpers ---------------------------------------------------------

    def _my_contact_ids(self):
        """Subquery of contact ids assigned to the caller."""
        return (
            select(Contact.id)
            .where(Contact.owner_id == self.principal.id)
            .where(Contact.deleted_at.is_(None))
            .scalar_subquery()
        )

    # -- entities --------------------------------------------------------

    def contacts(self) -> Select:
        """Owner: firm-wide. Agent / Cold Caller: strictly their own leads.

        This ``WHERE owner_id = :me`` is baked into the statement itself, so it
        applies identically to a list request, a detail request, an export
        attempt, and any future endpoint -- there is no code path that reads
        contacts without it.
        """
        stmt = select(Contact).where(Contact.deleted_at.is_(None))
        if not self.principal.sees_everything:
            stmt = stmt.where(Contact.owner_id == self.principal.id)
        return _mark(stmt)

    def properties(self) -> Select:
        """Inventory is firm-wide readable by every role (permission matrix).

        Write access is restricted at the endpoint layer: Cold Callers may read
        but not add or edit listings.
        """
        return _mark(select(Property).where(Property.deleted_at.is_(None)))

    def property_interests(self) -> Select:
        """"Who showed what to whom".

        Owner sees every showing; an Agent sees only showings they performed;
        a Cold Caller has no access to this view at all.
        """
        stmt = select(PropertyInterest)
        if self.principal.sees_everything:
            return _mark(stmt)
        if self.principal.role == ROLE_AGENT:
            return _mark(
                stmt.where(PropertyInterest.shown_by_agent_id == self.principal.id)
            )
        return _mark(stmt.where(false()))

    def call_logs(self) -> Select:
        """Calls the caller placed, plus calls on leads they own."""
        stmt = select(CallLog)
        if self.principal.sees_everything:
            return _mark(stmt)
        return _mark(
            stmt.where(
                (CallLog.caller_id == self.principal.id)
                | (CallLog.contact_id.in_(self._my_contact_ids()))
            )
        )

    def activities(self) -> Select:
        """Own activity, plus activity recorded against the caller's own leads.

        The second clause is what makes a lead's timeline complete after a
        reassignment; it cannot expose another agent's leads because the
        contact subquery is itself scoped to the caller.
        """
        stmt = select(Activity)
        if self.principal.sees_everything:
            return _mark(stmt)
        return _mark(
            stmt.where(
                (Activity.user_id == self.principal.id)
                | (Activity.contact_id.in_(self._my_contact_ids()))
            )
        )

    def tasks(self) -> Select:
        stmt = select(Task)
        if self.principal.sees_everything:
            return _mark(stmt)
        return _mark(stmt.where(Task.assigned_to == self.principal.id))

    def audit_log(self) -> Select:
        """Owner only. Everyone else gets an empty result set."""
        stmt = select(AuditLog)
        if self.principal.sees_everything:
            return _mark(stmt)
        return _mark(stmt.where(false()))

    # -- WhatsApp ingestion (Phase 3) ------------------------------------

    def whatsapp_groups(self, *, include_removed: bool = False) -> Select:
        """Owner only. ROLES_PERMISSIONS.md: "Configure WhatsApp ingestion
        groups -- Owner ✅, Manager/Agent/Cold Caller ❌".

        Staff read the *inventory* the feed produces, never the feed's
        plumbing: which groups the firm sits in is competitive information,
        and it is the one list that would let a departing agent reconstruct
        the firm's sourcing network.
        """
        stmt = select(WhatsAppGroup)
        if not include_removed:
            stmt = stmt.where(WhatsAppGroup.deleted_at.is_(None))
        if self.principal.sees_everything:
            return _mark(stmt)
        return _mark(stmt.where(false()))

    def whatsapp_messages(self) -> Select:
        """Owner only -- raw group traffic, including messages that turned out
        not to be listings at all."""
        stmt = select(WhatsAppMessage)
        if self.principal.sees_everything:
            return _mark(stmt)
        return _mark(stmt.where(false()))

    def property_sources(self) -> Select:
        """Provenance for a listing: which groups it appeared in, posted by
        whom, how many times.

        Readable by every role, matching ``properties`` itself -- an agent
        working a flat needs the posting broker's number to act on it, and
        seeing that the same unit was reposted six times is exactly the signal
        that tells them it is stale or distressed.
        """
        return _mark(select(PropertySource))

    def users(self, *, include_deactivated: bool = False) -> Select:
        """Owner sees all staff; everyone else sees only themselves.

        ``include_deactivated`` exists so the Owner's user-management screen can
        see and reactivate departed staff; it does not widen row visibility for
        any other role.
        """
        stmt = select(User)
        if not include_deactivated:
            stmt = stmt.where(User.deleted_at.is_(None))
        if self.principal.sees_everything:
            return _mark(stmt)
        return _mark(stmt.where(User.id == self.principal.id))


# ---------------------------------------------------------------------------
# Phase 1 note on the Manager role
# ---------------------------------------------------------------------------
# ROLES_PERMISSIONS.md allows Phase 1 to ship without Manager, "collapsing
# 'Team only' rows to ❌". The role constant exists in the data model, but
# `sees_everything` is Owner-only, so a manager row -- if one were created out
# of band -- is scoped as narrowly as an Agent. Fail closed, then widen
# deliberately in Phase 2 when team scoping is actually built and tested.
