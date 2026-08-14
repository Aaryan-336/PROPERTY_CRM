"""Let one lead be worked by several staff members.

``contacts.owner_id`` models a lead as belonging to exactly one person, which is
right for accountability and for building the call queue, but wrong for how a
brokerage actually works a good lead: the owner brings in a closer, or splits
two site visits between two agents, and until now the only way to express that
was to reassign the lead and take it away from whoever had it.

This table is additive — owner_id keeps its meaning and nothing about the
existing queue changes. An assignment grants a second kind of access, and
``app/scoping.py`` widens its contacts predicate to honour it: a staff member
now sees a lead they own *or* one they have been assigned.

Deliberately rows rather than an array column on contacts. Each assignment
records who made it and when, which is what makes it readable in the audit log,
and the scoping predicate has to select against it.

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "balaji_app"


def _role_exists(role: str) -> bool:
    """True when `role` is a real Postgres role on this cluster."""
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        .scalar()
    )


def upgrade() -> None:
    op.create_table(
        "contact_assignments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "contact_id",
            sa.BigInteger(),
            sa.ForeignKey("contacts.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("assigned_by", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Assigning the same person twice is a no-op, not a second assignment.
        sa.UniqueConstraint("contact_id", "user_id", name="uq_assignment_pair"),
    )
    # Both directions are hot: scoping looks up by user on every contact read,
    # the lead screen looks up by contact.
    op.create_index("idx_assignments_user", "contact_assignments", ["user_id"])
    op.create_index("idx_assignments_contact", "contact_assignments", ["contact_id"])

    # Guarded like 0001-0003: managed Postgres has a single owner role and no
    # balaji_app, and an unguarded GRANT fails the whole migration.
    if not _role_exists(APP_ROLE):
        print(f"[0005] role {APP_ROLE!r} not present - skipping GRANT.")
        return
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE contact_assignments "
        f"TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("idx_assignments_contact", table_name="contact_assignments")
    op.drop_index("idx_assignments_user", table_name="contact_assignments")
    op.drop_table("contact_assignments")
