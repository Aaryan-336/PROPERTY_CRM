"""Audit log reader. Owner only, read-only, no write or delete surface at all."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.deps import PageDep, ScopedDep, SessionDep, rate_limit_lists, require
from app.models import AuditLog
from app.schemas import AuditOut, Paged
from app.serializers import user_names

router = APIRouter(tags=["audit"])


@router.get(
    "/audit-log",
    response_model=Paged[AuditOut],
    dependencies=[Depends(require("audit.read")), Depends(rate_limit_lists)],
)
def list_audit(
    scoped: ScopedDep,
    db: SessionDep,
    page: PageDep,
    user_id: int | None = None,
    resource_type: str | None = None,
    action: str | None = None,
    resource_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Paged[AuditOut]:
    stmt = scoped.audit_log()
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_id is not None:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if since:
        stmt = stmt.where(AuditLog.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditLog.occurred_at <= until)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(AuditLog.occurred_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    names = user_names(db, [r.user_id for r in rows])

    items = []
    for r in rows:
        item = AuditOut.model_validate(r)
        item.user_name = names.get(r.user_id)
        items.append(item)

    return Paged[AuditOut](
        items=items,
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )
