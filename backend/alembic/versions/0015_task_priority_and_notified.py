"""Reminder importance, and a record of when each reminder's push went out.

`notified_at` is what makes delivery exactly-once: the dispatcher claims a
reminder by stamping it, so neither a second process nor a restart sends it
twice. Existing reminders already past due are stamped here so the first run
does not wake everyone with a backlog of stale pings.

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("priority", sa.Text(), nullable=False, server_default="normal"),
    )
    op.add_column("tasks", sa.Column("notified_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE tasks SET notified_at = now() "
        "WHERE status <> 'pending' OR (due_at IS NOT NULL AND due_at <= now())"
    )
    op.create_index(
        "idx_tasks_reminder_queue",
        "tasks",
        ["due_at"],
        postgresql_where=sa.text("status = 'pending' AND notified_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_tasks_reminder_queue", table_name="tasks")
    op.drop_column("tasks", "notified_at")
    op.drop_column("tasks", "priority")
