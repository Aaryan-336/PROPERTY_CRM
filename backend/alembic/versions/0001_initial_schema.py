"""Phase 1 schema.

Tables and indexes follow docs/DATA_MODEL.md. The final step grants the
application role the rights it needs and, critically, withholds UPDATE and
DELETE on audit_log so history cannot be rewritten with the app's own
credentials (SECURITY_MODEL.md §"Audit logging").

Revision ID: 0001
Revises:
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
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
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), unique=True),
        sa.Column("phone", sa.Text()),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("manager_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("is_available", sa.Boolean(), server_default=sa.true()),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("phone_masked", sa.Boolean(), server_default=sa.false()),
        sa.Column("lead_source", sa.Text()),
        sa.Column("campaign", sa.Text()),
        sa.Column("budget_min", sa.Numeric(14, 2)),
        sa.Column("budget_max", sa.Numeric(14, 2)),
        sa.Column("preferred_locations", postgresql.ARRAY(sa.Text())),
        sa.Column("property_type_interest", sa.Text()),
        sa.Column("buyer_type", sa.Text()),
        sa.Column("lead_score", sa.Integer(), server_default="0"),
        sa.Column("stage", sa.Text(), server_default="new"),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_contacts_owner", "contacts", ["owner_id"])
    op.create_index(
        "idx_contacts_phone",
        "contacts",
        ["phone"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "properties",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("title", sa.Text()),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("building", sa.Text()),
        sa.Column("property_type", sa.Text()),
        sa.Column("listing_type", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(14, 2)),
        sa.Column("status", sa.Text(), server_default="available"),
        sa.Column("source", sa.Text(), server_default="manual"),
        sa.Column("raw_message", sa.Text()),
        sa.Column("source_group", sa.Text()),
        sa.Column("posted_by_agent_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_properties_location", "properties", ["location"])
    op.create_index("idx_properties_listing_type", "properties", ["listing_type"])
    op.create_index("idx_properties_price", "properties", ["price"])

    op.create_table(
        "property_interests",
        sa.Column("contact_id", sa.BigInteger(), sa.ForeignKey("contacts.id")),
        sa.Column("property_id", sa.BigInteger(), sa.ForeignKey("properties.id")),
        sa.Column("shown_by_agent_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("interest_level", sa.Text()),
        sa.Column(
            "shown_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("contact_id", "property_id", "shown_at"),
    )

    op.create_table(
        "call_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("contact_id", sa.BigInteger(), sa.ForeignKey("contacts.id")),
        sa.Column(
            "caller_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("temperature", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("flagged_for_owner", sa.Boolean(), server_default=sa.false()),
        sa.Column("follow_up_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_call_logs_contact",
        "call_logs",
        ["contact_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_call_logs_flagged",
        "call_logs",
        ["flagged_for_owner"],
        postgresql_where=sa.text("flagged_for_owner = TRUE"),
    )

    op.create_table(
        "activities",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("contact_id", sa.BigInteger(), sa.ForeignKey("contacts.id")),
        sa.Column("property_id", sa.BigInteger(), sa.ForeignKey("properties.id")),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_activities_contact",
        "activities",
        ["contact_id", sa.text("occurred_at DESC")],
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.BigInteger()),
        sa.Column("detail", postgresql.JSONB()),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_audit_log_user", "audit_log", ["user_id", sa.text("occurred_at DESC")]
    )
    op.create_index(
        "idx_audit_log_resource", "audit_log", ["resource_type", "resource_id"]
    )

    # ---- additive tables (documented deviations from DATA_MODEL.md) ----

    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.Text()),
    )
    op.create_index("idx_sessions_user", "sessions", ["user_id", "revoked_at"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("contact_id", sa.BigInteger(), sa.ForeignKey("contacts.id")),
        sa.Column(
            "assigned_to", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "source_call_log_id", sa.BigInteger(), sa.ForeignKey("call_logs.id")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "idx_tasks_assignee_due", "tasks", ["assigned_to", "status", "due_at"]
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )

    _apply_grants()


def _apply_grants() -> None:
    """Give the app role exactly what it needs, and nothing more.

    audit_log gets INSERT and SELECT only. With no UPDATE or DELETE grant,
    Postgres refuses to rewrite history even if application code (or someone
    holding the app's credentials) tries to.

    Skipped when the app role does not exist. Managed Postgres (Render, Neon,
    Supabase, RDS) hands you a single owner role, and a bare ``GRANT ... TO
    balaji_app`` against a role that was never created aborts the whole
    migration — which would make the schema undeployable on every one of them.

    The trade-off is real and worth stating: on a single-role deployment the
    append-only guarantee on audit_log drops from "Postgres refuses" to "the
    application never issues the statement". ``app/models.py`` and
    ``app/audit.py`` still never emit an UPDATE or DELETE against it. To get
    the database-level guarantee back, create the role and re-run this:

        CREATE ROLE balaji_app LOGIN PASSWORD '<password>';
        -- then point DATABASE_URL at balaji_app and re-run `alembic upgrade head`

    See docs/DEPLOYMENT.md.
    """
    if not _role_exists(APP_ROLE):
        print(
            f"[0001] role {APP_ROLE!r} not present - skipping GRANT/REVOKE. "
            "audit_log append-only is enforced by application code only. "
            "See docs/DEPLOYMENT.md to restore the database-level guarantee."
        )
        return

    writable = (
        "users",
        "contacts",
        "properties",
        "property_interests",
        "call_logs",
        "activities",
        "sessions",
        "tasks",
        "push_subscriptions",
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    for table in writable:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}"
        )
    op.execute(f"GRANT SELECT, INSERT ON TABLE audit_log TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON TABLE audit_log FROM {APP_ROLE}")
    op.execute(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}"
    )


def downgrade() -> None:
    for table in (
        "push_subscriptions",
        "tasks",
        "sessions",
        "audit_log",
        "activities",
        "call_logs",
        "property_interests",
        "properties",
        "contacts",
        "users",
    ):
        op.drop_table(table)
