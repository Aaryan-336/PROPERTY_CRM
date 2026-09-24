"""Per-user Meta Ads authorization, token stored encrypted.

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
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
    op.create_table(
        "meta_ad_connections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("meta_user_id", sa.Text()),
        sa.Column("meta_user_name", sa.Text()),
        sa.Column("access_token_enc", sa.Text()),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("scopes", postgresql.ARRAY(sa.Text())),
        sa.Column("ad_account_id", sa.Text()),
        sa.Column("ad_account_name", sa.Text()),
        sa.Column("ad_account_currency", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column("oauth_state_hash", sa.Text()),
        sa.Column("oauth_state_expires_at", sa.DateTime(timezone=True)),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_meta_oauth_state",
        "meta_ad_connections",
        ["oauth_state_hash"],
        postgresql_where=sa.text("oauth_state_hash IS NOT NULL"),
    )

    if not _role_exists(APP_ROLE):
        print(f"[0013] role {APP_ROLE!r} not present - skipping GRANT.")
        return
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE meta_ad_connections TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("idx_meta_oauth_state", table_name="meta_ad_connections")
    op.drop_table("meta_ad_connections")
