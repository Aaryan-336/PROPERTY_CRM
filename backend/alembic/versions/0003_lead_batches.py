"""Group imported calling lists into batches, and separate call targets from leads.

An imported spreadsheet row is a phone number someone bought, not a lead. Until
this migration the two were indistinguishable the moment the import committed:
rows landed straight in the contacts table, mixed in with walk-ins and
referrals, and the question "was that list worth buying" had no answer left in
the data.

Three changes carry that separation:

  * `lead_batches` — one row per upload, holding the counts as parsed. The
    rejected rows matter as much as the accepted ones; "600 in, 480 usable" is
    the comparison between two vendors, and it is gone once duplicates are
    dropped.
  * `contacts.batch_id` — which list a number came from.
  * `contacts.is_lead` — whether anyone has decided it is a lead yet.

`is_lead` defaults to true, and the backfill leaves every existing contact
alone. That is deliberate: everything already in the table arrived through a
route that implies qualification, and flipping them to false would empty the
leads pipeline on deploy. Only rows created by an import from here on start
false.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
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
        "lead_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text()),
        sa.Column("uploaded_by_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )

    op.add_column(
        "contacts",
        sa.Column(
            "is_lead", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column(
        "contacts",
        sa.Column("batch_id", sa.BigInteger(), sa.ForeignKey("lead_batches.id")),
    )
    op.create_index("idx_contacts_batch", "contacts", ["batch_id", "is_lead"])

    op.add_column(
        "call_logs",
        sa.Column(
            "marked_lead", sa.Boolean(), server_default=sa.text("false")
        ),
    )

    # Same posture as 0001 and 0002: the app role gets DML on operational
    # tables, and audit_log keeps its insert-only grant untouched.
    if not _role_exists(APP_ROLE):
        print(f"[0003] role {APP_ROLE!r} not present - skipping GRANT.")
        return
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE lead_batches TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_column("call_logs", "marked_lead")
    op.drop_index("idx_contacts_batch", table_name="contacts")
    op.drop_column("contacts", "batch_id")
    op.drop_column("contacts", "is_lead")
    op.drop_table("lead_batches")
