"""Shared FastAPI dependencies: authentication, scoping, pagination, throttling."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import get_session, system_scope
from app.errors import forbidden, rate_limited, unauthorized
from app.models import Session as SessionRow
from app.models import User
from app.rbac import has
from app.scoping import Principal, ScopedQuery
from app.security import decode_token

SessionDep = Annotated[DbSession, Depends(get_session)]


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    # The PWA talks to this API through a Next.js route handler that holds the
    # JWT in an httpOnly cookie; the cookie fallback keeps direct browser calls
    # working in development without a second auth path.
    return request.cookies.get("balaji_session")


def current_principal(request: Request, db: SessionDep) -> Principal:
    """Resolve the caller, verifying the token's session row is still live."""
    token = _bearer_token(request)
    if not token:
        raise unauthorized()

    claims = decode_token(token)
    if not claims:
        raise unauthorized("Session expired or token invalid. Please sign in again.")

    jti = claims.get("jti")
    user_id = claims.get("sub")
    if not jti or not user_id:
        raise unauthorized("Malformed token.")

    # Trusted infrastructure read: resolving who the caller is necessarily
    # precedes having a principal to scope by.
    with system_scope():
        row = db.execute(
            select(SessionRow, User)
            .join(User, User.id == SessionRow.user_id)
            .where(SessionRow.jti == jti)
        ).first()

    if row is None:
        raise unauthorized("Session not recognised.")

    session_row, user = row
    now = datetime.now(timezone.utc)
    if session_row.revoked_at is not None:
        raise unauthorized("Session has been signed out.")
    if session_row.expires_at <= now:
        raise unauthorized("Session expired. Please sign in again.")
    if user.deleted_at is not None:
        raise unauthorized("This account has been deactivated.")
    if str(user.id) != str(user_id):
        raise unauthorized("Token does not match its session.")

    principal = Principal(
        id=user.id, name=user.name, role=user.role, manager_id=user.manager_id
    )
    # The audit middleware runs outside the dependency graph and reads the
    # principal from request state.
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def scoped(principal: PrincipalDep) -> ScopedQuery:
    return ScopedQuery(principal)


ScopedDep = Annotated[ScopedQuery, Depends(scoped)]


def require(capability: str) -> Callable[..., Principal]:
    """Dependency factory enforcing a capability from the permission matrix."""

    def _dep(principal: PrincipalDep) -> Principal:
        if not has(principal, capability):
            raise forbidden(
                f"Role '{principal.role}' does not have the "
                f"'{capability}' capability."
            )
        return principal

    return _dep


# ---------------------------------------------------------------------------
# Pagination -- capped, because page size is a security control here
# (SECURITY_MODEL.md §4), bounding how much of the client list one request
# can return and making bulk scraping slow and visible in the audit log.
# ---------------------------------------------------------------------------


class Page:
    def __init__(self, limit: int, offset: int) -> None:
        self.limit = limit
        self.offset = offset


def pagination(
    limit: int = Query(
        default=settings.default_page_size,
        ge=1,
        le=settings.max_page_size,
        description=f"Rows per page. Hard cap {settings.max_page_size}.",
    ),
    offset: int = Query(default=0, ge=0),
) -> Page:
    return Page(limit=min(limit, settings.max_page_size), offset=offset)


PageDep = Annotated[Page, Depends(pagination)]


# ---------------------------------------------------------------------------
# Rate limiting on list endpoints
# ---------------------------------------------------------------------------
# SECURITY_MODEL.md accepts that page-by-page manual copying cannot be fully
# prevented, only made slower and more visible. This in-process limiter serves
# the "slower" half; the audit log serves the "visible" half. A single-process
# deployment for one small brokerage makes in-memory state adequate -- move
# this to Redis if the API is ever run multi-worker.

_hits: dict[int, deque[float]] = defaultdict(deque)


def rate_limit_lists(principal: PrincipalDep) -> None:
    window_start = time.monotonic() - 60.0
    bucket = _hits[principal.id]
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= settings.list_rate_limit_per_minute:
        raise rate_limited(
            "Too many list requests in the past minute. This limit exists to "
            "slow bulk collection of contact data."
        )
    bucket.append(time.monotonic())


def reset_rate_limits() -> None:
    """Test helper."""
    _hits.clear()
