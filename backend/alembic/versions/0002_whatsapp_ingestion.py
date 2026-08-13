"""Phase 3 -- WhatsApp Property Feed Aggregator.

Adds the ingestion tables (`whatsapp_groups`, `whatsapp_messages`,
`property_sources`) and the extraction columns on `properties` that dedup needs
to tell a 2BHK from the 3BHK upstairs. See app/models.py for why each exists.

Additive only: every new `properties` column is nullable, so rows created in
Phase 1 stay valid and a manually-entered listing is unaffected.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "balaji_app"


def _role_exists(role: str) -> bool:
    """True when `role` is a real Postgres role on this cluster.

    0001 checks this before granting; this migration did not, and on managed
    Postgres — which hands you a single owner role and no balaji_app — the
    GRANT below aborted the deploy with `role "balaji_app" does not exist`.
    """
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        .scalar()
    )


NEW_TABLES = ("whatsapp_groups", "whatsapp_messages", "property_sources")

PROPERTY_COLUMNS = (
    "bhk",
    "area_sqft",
    "furnishing",
    "contact_name",
    "contact_phone",
    "dedupe_key",
    "extraction_confidence",
    "review_state",
    "last_seen_at",
)


def upgrade() -> None:
    # ---- properties: extraction + dedup columns --------------------------
    op.add_column("properties", sa.Column("bhk", sa.Integer()))
    op.add_column("properties", sa.Column("area_sqft", sa.Integer()))
    op.add_column("properties", sa.Column("furnishing", sa.Text()))
    op.add_column("properties", sa.Column("contact_name", sa.Text()))
    op.add_column("properties", sa.Column("contact_phone", sa.Text()))
    op.add_column("properties", sa.Column("dedupe_key", sa.Text()))
    op.add_column("properties", sa.Column("extraction_confidence", sa.Float()))
    op.add_column("properties", sa.Column("review_state", sa.Text()))
    op.add_column(
        "properties", sa.Column("last_seen_at", sa.DateTime(timezone=True))
    )

    # Partial index: dedup only ever looks up live listings, and excluding
    # soft-deleted rows keeps a merged-away listing from resurrecting as a
    # match candidate.
    op.create_index(
        "idx_properties_dedupe_key",
        "properties",
        ["dedupe_key"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("idx_properties_source", "properties", ["source"])

    # ---- whatsapp_groups -------------------------------------------------
    op.create_table(
        "whatsapp_groups",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("group_jid", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("note", sa.Text()),
        sa.Column("added_by", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column(
            "message_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "listing_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_whatsapp_groups_active", "whatsapp_groups", ["is_active"])

    # ---- whatsapp_messages -----------------------------------------------
    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            sa.ForeignKey("whatsapp_groups.id"),
            nullable=False,
        ),
        # Idempotency key for the ingest endpoint. The gateway replays its
        # buffer after a reconnect; without this a dropped WhatsApp session
        # would duplicate inventory on every recovery.
        sa.Column("wa_message_id", sa.Text(), nullable=False, unique=True),
        sa.Column("sender_jid", sa.Text()),
        sa.Column("sender_name", sa.Text()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="pending"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("extraction", postgresql.JSONB()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "listings_found", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "listings_new", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_index(
        "idx_whatsapp_messages_queue",
        "whatsapp_messages",
        ["status", "received_at"],
    )
    op.create_index(
        "idx_whatsapp_messages_group",
        "whatsapp_messages",
        ["group_id", sa.text("received_at DESC")],
    )

    # ---- property_sources ------------------------------------------------
    op.create_table(
        "property_sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "property_id",
            sa.BigInteger(),
            sa.ForeignKey("properties.id"),
            nullable=False,
        ),
        sa.Column(
            "message_id", sa.BigInteger(), sa.ForeignKey("whatsapp_messages.id")
        ),
        sa.Column(
            "group_id", sa.BigInteger(), sa.ForeignKey("whatsapp_groups.id")
        ),
        sa.Column("group_name", sa.Text()),
        sa.Column("posted_by_name", sa.Text()),
        sa.Column("posted_by_phone", sa.Text()),
        sa.Column("raw_message", sa.Text()),
        sa.Column(
            "relation", sa.Text(), nullable=False, server_default="origin"
        ),
        sa.Column("match_score", sa.Float()),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Re-running the extractor over an already-processed message must not
        # inflate a listing's repost count.
        sa.UniqueConstraint("property_id", "message_id", name="uq_property_source"),
    )
    op.create_index(
        "idx_property_sources_property",
        "property_sources",
        ["property_id", sa.text("seen_at DESC")],
    )

    # ---- grants ----------------------------------------------------------
    # Same posture as 0001: the app role gets DML on operational tables. It
    # still holds no UPDATE/DELETE on audit_log, and nothing here changes that.
    #
    # Guarded like 0001. Managed Postgres (Render, Supabase, RDS) gives a single
    # owner role, so balaji_app does not exist there and an unguarded GRANT
    # fails the whole migration — which is exactly what it did.
    if not _role_exists(APP_ROLE):
        print(f"[0002] role {APP_ROLE!r} not present - skipping GRANT.")
        return

    for table in NEW_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}"
        )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("property_sources")
    op.drop_table("whatsapp_messages")
    op.drop_table("whatsapp_groups")

    op.drop_index("idx_properties_source", table_name="properties")
    op.drop_index("idx_properties_dedupe_key", table_name="properties")
    for column in PROPERTY_COLUMNS:
        op.drop_column("properties", column)
