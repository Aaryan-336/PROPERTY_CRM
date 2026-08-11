"""Follow-up tasks and reminders (FEATURE_LIST P1)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.deps import (
    PageDep,
    PrincipalDep,
    ScopedDep,
    SessionDep,
    rate_limit_lists,
)
from app.errors import not_found
from app.models import Contact, Task
from app.schemas import Paged, TaskCreateRequest, TaskOut, TaskUpdateRequest
from app.serializers import user_names

router = APIRouter(tags=["tasks"])


def _serialize(db: SessionDep, scoped: ScopedDep, rows: list[Task]) -> list[TaskOut]:
    if not rows:
        return []
    names = user_names(db, [r.assigned_to for r in rows])
    contact_ids = {r.contact_id for r in rows if r.contact_id}
    contacts = (
        {
            c.id: c.full_name
            for c in db.execute(
                scoped.contacts().where(Contact.id.in_(contact_ids))
            ).scalars()
        }
        if contact_ids
        else {}
    )
    out = []
    for r in rows:
        item = TaskOut.model_validate(r)
        item.assigned_to_name = names.get(r.assigned_to)
        item.contact_name = contacts.get(r.contact_id) if r.contact_id else None
        out.append(item)
    return out


@router.get(
    "/tasks", response_model=Paged[TaskOut], dependencies=[Depends(rate_limit_lists)]
)
def list_tasks(
    scoped: ScopedDep,
    db: SessionDep,
    page: PageDep,
    status: str | None = Query(default="pending"),
    contact_id: int | None = None,
    overdue_only: bool = False,
) -> Paged[TaskOut]:
    stmt = scoped.tasks()
    if status:
        stmt = stmt.where(Task.status == status)
    if contact_id is not None:
        stmt = stmt.where(Task.contact_id == contact_id)
    if overdue_only:
        stmt = stmt.where(Task.due_at.is_not(None), Task.due_at <= datetime.now(timezone.utc))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        .scalars()
        .all()
    )
    return Paged[TaskOut](
        items=_serialize(db, scoped, list(rows)),
        total=total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.offset + len(rows) < total,
    )


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreateRequest,
    scoped: ScopedDep,
    db: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> TaskOut:
    if payload.contact_id is not None:
        contact = db.execute(
            scoped.contacts().where(Contact.id == payload.contact_id)
        ).scalar_one_or_none()
        if contact is None:
            raise not_found("Contact")

    task = Task(
        contact_id=payload.contact_id,
        assigned_to=principal.id,
        created_by=principal.id,
        title=payload.title,
        due_at=payload.due_at,
        status="pending",
    )
    db.add(task)
    db.commit()
    request.state.audit.set_resource(task.id)
    return _serialize(db, scoped, [task])[0]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    payload: TaskUpdateRequest,
    scoped: ScopedDep,
    db: SessionDep,
    request: Request,
) -> TaskOut:
    task = db.execute(
        scoped.tasks().where(Task.id == task_id)
    ).scalar_one_or_none()
    if task is None:
        raise not_found("Task")

    fields = payload.model_dump(exclude_unset=True)
    before = {k: getattr(task, k) for k in fields}
    for key, value in fields.items():
        setattr(task, key, value)
    if fields.get("status") == "done" and task.completed_at is None:
        task.completed_at = datetime.now(timezone.utc)
    db.commit()

    request.state.audit.record_changes(before, fields)
    return _serialize(db, scoped, [task])[0]
