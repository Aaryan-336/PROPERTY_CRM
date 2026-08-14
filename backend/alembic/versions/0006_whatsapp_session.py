"""Let the owner pair WhatsApp from the browser instead of a terminal.

Pairing was `npm run pair` on whatever box runs the gateway, scanning a QR
printed as ASCII art. That works for whoever deployed it and is useless for the
owner, who is the person actually holding the phone that has to scan.

One row. The gateway writes its connection state and current QR here; the
owner's screen polls it. The QR is stored with an expiry because WhatsApp
rotates it every twenty seconds or so, and a stale QR that still renders is
worse than showing none — it fails on the phone with no explanation.

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
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
        "whatsapp_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "state", sa.Text(), nullable=False, server_default="disconnected"
        ),
        sa.Column("qr", sa.Text()),
        sa.Column("qr_expires_at", sa.DateTime(timezone=True)),
        sa.Column("jid", sa.Text()),
        sa.Column("display_name", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Seeded so every read is a plain UPDATE and the API never has to decide
    # whether to insert — there is exactly one session and it always exists.
    op.execute("INSERT INTO whatsapp_session (id, state) VALUES (1, 'disconnected')")

    if not _role_exists(APP_ROLE):
        print(f"[0006] role {APP_ROLE!r} not present - skipping GRANT.")
        return
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE whatsapp_session TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("whatsapp_session")
