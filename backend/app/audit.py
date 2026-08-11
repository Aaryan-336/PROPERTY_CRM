"""Structural audit logging.

SECURITY_MODEL.md: "implemented as FastAPI middleware wrapping all requests
touching contacts, properties, call_logs, and any export endpoint -- individual
endpoint handlers don't need to remember to log, so nothing gets missed."

The design follows that literally. The middleware decides *on its own* whether
a request is auditable, from the request path and method, and writes the row
after the response is produced. No endpoint opts in; no endpoint can opt out.
A handler may *enrich* the entry -- naming which fields changed, how many rows
an export returned -- by writing to ``request.state.audit_detail``, but if it
enriches nothing the entry is still written.

Two consequences worth stating plainly:

* Failed and rejected requests are logged too, with their status code. An Agent
  probing ``GET /contacts/{id}`` for ids they do not own produces a trail of
  404s under their user id, which is precisely the insider behaviour this log
  exists to surface.
* The audit row is committed in its own session, independent of the request's
  transaction. A write that rolls back still leaves evidence that it was
  attempted.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session as DbSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.db import SessionLocal
from app.models import AuditLog

# Path prefix -> resource_type recorded in the audit log.
# Ordered longest-first so that '/contacts/export' beats '/contacts'.
_RESOURCE_ROUTES: tuple[tuple[str, str], ...] = (
    ("/contacts/export", "contact"),
    ("/contacts/bulk-import", "contact"),
    ("/contacts", "contact"),
    ("/properties", "property"),
    ("/property-interests", "property_interest"),
    ("/call-queue", "call_log"),
    ("/calls", "call_log"),
    ("/owner/escalations", "call_log"),
    ("/activities", "activity"),
    ("/tasks", "task"),
    ("/audit-log", "audit_log"),
    ("/users", "user"),
    # Phase 3. The internal ingest webhook is deliberately absent: it has no
    # principal to attribute an entry to, and audit_log.user_id is NOT NULL.
    # Its trail is the whatsapp_messages table itself, which records every
    # message the gateway delivered.
    ("/whatsapp", "whatsapp_group"),
)

_ID_IN_PATH = re.compile(r"^/[^/]+/(\d+)")


class AuditContext:
    """Per-request enrichment surface for handlers.

    Handlers reach this via ``request.state.audit``. Everything on it is
    optional; the entry is written regardless of whether it is touched.
    """

    def __init__(self) -> None:
        self.resource_id: int | None = None
        self.detail: dict[str, Any] = {}
        self.action_override: str | None = None

    def set_resource(self, resource_id: int | None) -> None:
        self.resource_id = resource_id

    def add(self, **fields: Any) -> None:
        self.detail.update(fields)

    def record_changes(self, before: dict[str, Any], after: dict[str, Any]) -> None:
        """Record which fields changed, old -> new, for an update."""
        changed = {
            key: {"from": _jsonable(before.get(key)), "to": _jsonable(value)}
            for key, value in after.items()
            if before.get(key) != value
        }
        if changed:
            self.detail["changed_fields"] = changed


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def resolve_resource_type(path: str) -> str | None:
    for prefix, resource_type in _RESOURCE_ROUTES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(
            prefix + "?"
        ):
            return resource_type
    return None


def resolve_action(method: str, path: str) -> str:
    """Map an HTTP request onto the audit action vocabulary.

    'view', 'edit', 'export', 'delete' and 'reassign' come from DATA_MODEL.md.
    'create' is added so the owner can tell a new record from a modified one --
    an audit log that collapses the two answers fewer questions.
    """
    if path.endswith("/export"):
        return "export"
    if path.endswith("/reassign"):
        return "reassign"
    if path.endswith("/bulk-import"):
        return "import"
    method = method.upper()
    if method == "GET":
        return "view"
    if method == "POST":
        return "create"
    if method in ("PATCH", "PUT"):
        return "edit"
    if method == "DELETE":
        return "delete"
    return method.lower()


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        resource_type = resolve_resource_type(path)

        context = AuditContext()
        request.state.audit = context

        response = await call_next(request)

        if resource_type is None:
            return response

        # An unauthenticated request has no identity to attribute the entry to,
        # and audit_log.user_id is NOT NULL. Those are visible in the access log
        # instead.
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return response

        action = context.action_override or resolve_action(request.method, path)

        detail: dict[str, Any] = {
            "method": request.method,
            "path": path,
            "status": response.status_code,
        }
        if request.url.query:
            detail["query"] = request.url.query
        detail.update(context.detail)

        resource_id = context.resource_id
        if resource_id is None:
            match = _ID_IN_PATH.match(path)
            if match:
                resource_id = int(match.group(1))

        _write_entry(
            user_id=principal.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
        return response


def _write_entry(
    *,
    user_id: int,
    action: str,
    resource_type: str,
    resource_id: int | None,
    detail: dict[str, Any],
) -> None:
    db: DbSession = SessionLocal()
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                detail=detail,
            )
        )
        db.commit()
    except Exception:  # pragma: no cover - audit must never break a request
        db.rollback()
        # Losing an audit row is bad, but taking the app down with it is worse
        # for a field team mid-shift. Surface it in the process log instead.
        import logging

        logging.getLogger("balaji.audit").exception(
            "Failed to write audit entry for user=%s action=%s resource=%s/%s",
            user_id,
            action,
            resource_type,
            resource_id,
        )
    finally:
        db.close()
