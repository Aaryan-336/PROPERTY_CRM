"""Meta Lead Ads intake and Instagram reel suggestions.

Adds the Page / Instagram account a connection leads from, and `meta_leads`:
one row per lead Meta delivers, kept verbatim next to the contact it became.
`leadgen_id` is unique, which is what makes Meta's at-least-once webhook
delivery (and our own backfill) safe to repeat.

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

APP_ROLE = "balaji_app"


def _role_exists(role: str) -> bool:
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        .scalar()
    )


def upgrade() -> None:
    for name in ("page_id", "page_name", "instagram_id", "instagram_username"):
        op.add_column("meta_ad_connections", sa.Column(name, sa.Text()))
    op.add_column(
        "meta_ad_connections",
        sa.Column("page_subscribed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "meta_leads",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("leadgen_id", sa.Text(), nullable=False, unique=True),
        sa.Column("page_id", sa.Text()),
        sa.Column("form_id", sa.Text()),
        sa.Column("campaign_id", sa.Text()),
        sa.Column("campaign_name", sa.Text()),
        sa.Column("adset_id", sa.Text()),
        sa.Column("ad_id", sa.Text()),
        sa.Column("ad_name", sa.Text()),
        sa.Column("platform", sa.Text()),
        sa.Column("field_data", postgresql.JSONB()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("contact_id", sa.BigInteger(), sa.ForeignKey("contacts.id")),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_created_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_meta_leads_campaign", "meta_leads", ["campaign_id"])
    op.create_index("idx_meta_leads_status", "meta_leads", ["status"])
    op.create_index("idx_meta_leads_contact", "meta_leads", ["contact_id"])

    if not _role_exists(APP_ROLE):
        print(f"[0016] role {APP_ROLE!r} not present - skipping GRANT.")
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE meta_leads TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("meta_leads")
    for name in (
        "page_subscribed_at",
        "instagram_username",
        "instagram_id",
        "page_name",
        "page_id",
    ):
        op.drop_column("meta_ad_connections", name)
