"""Database engine, session factory, and the unscoped-query guard.

The guard is the structural half of SECURITY_MODEL.md §1 ("enforce scoping in
the query layer, not just the UI"). ``app/scoping.py`` builds the pre-filtered
SELECTs; this module makes it impossible to *bypass* them by accident. Any ORM
query touching a guarded table that was not produced by ``ScopedQuery`` raises
``UnscopedQueryError`` before it reaches Postgres.

That inversion matters: a developer adding an endpoint next year does not have
to remember to apply a role filter. If they forget, the request fails loudly in
development rather than quietly returning another agent's leads in production.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import create_engine, event
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker

from app.config import settings
from app.models import (
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
    WhatsAppGroupCandidate,
    WhatsAppMessage,
)

engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class UnscopedQueryError(RuntimeError):
    """Raised when a guarded table is queried outside the scoping layer."""


# Every table whose rows belong to, or describe, a particular user. Reading any
# of these without a role scope is a bug by definition.
#
# The WhatsApp tables are guarded on a different rationale than the rest: their
# rows describe the firm's ingestion pipeline rather than a specific user, but
# ROLES_PERMISSIONS.md makes "configure WhatsApp ingestion groups" Owner-only,
# and the raw message bodies carry counterparty phone numbers the firm never
# chose to publish. Guarding them means a future endpoint that forgets to scope
# returns nothing rather than the raw feed.
GUARDED_MAPPERS = {
    Contact,
    Property,
    PropertyInterest,
    PropertySource,
    CallLog,
    Activity,
    AuditLog,
    Task,
    User,
    WhatsAppGroup,
    WhatsAppGroupCandidate,
    WhatsAppMessage,
}
GUARDED_TABLE_NAMES = {m.__tablename__ for m in GUARDED_MAPPERS}

# Set while running trusted infrastructure queries that legitimately predate a
# principal: authenticating a login, resolving a bearer token to a user,
# seeding, migrations.
_system_context: ContextVar[bool] = ContextVar("balaji_system_context", default=False)

SCOPE_MARKER = "balaji_scope_enforced"


@contextmanager
def system_scope() -> Iterator[None]:
    """Permit unscoped reads for trusted infrastructure work.

    Deliberately narrow and deliberately noisy to write: reaching for this in a
    request handler should feel like the wrong move, because it is.
    """
    token = _system_context.set(True)
    try:
        yield
    finally:
        _system_context.reset(token)


@event.listens_for(Session, "do_orm_execute")
def _enforce_scoping(state: ORMExecuteState) -> None:
    if not state.is_select:
        return
    if _system_context.get():
        return
    if state.execution_options.get(SCOPE_MARKER):
        return

    touched = {
        mapper.class_.__tablename__
        for mapper in state.all_mappers
        if hasattr(mapper.class_, "__tablename__")
    }
    offending = touched & GUARDED_TABLE_NAMES
    if offending:
        raise UnscopedQueryError(
            "Refusing to run a query against "
            f"{sorted(offending)} that did not come from ScopedQuery. "
            "Build the statement with the ScopedQuery dependency so the "
            "caller's role filter is applied at the SQL layer, or wrap "
            "genuine infrastructure work in db.system_scope()."
        )


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
