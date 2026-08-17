"""Let the owner start pairing, and pick groups from a list, without a terminal.

Two gaps remained after 0006 put the QR in the browser. Both of them still sent
the owner back to a command line:

* A QR only exists while the gateway is asking WhatsApp for one, and it only
  asks on a fresh session. If the saved session was already there, or had gone
  stale, the pairing screen sat empty forever with nothing the owner could press.
  ``pair_requested_at`` is that press: the owner asks, the gateway sees it on its
  next poll and starts a fresh pairing.

* Adding a group meant running ``npm run groups``, reading a
  ``120363…@g.us`` id out of the output and pasting it in. The gateway already
  knows every group the linked account is in, so it now uploads that list here
  and the owner picks from names instead of transcribing machine ids.

The candidate list is a cache of what WhatsApp told the gateway, not a
decision — a row here means "this group exists and could be watched". Watching
one still means a row in ``whatsapp_groups``, which is what the ingest webhook
checks and what the audit log records.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APP_ROLE = "balaji_app"


def _role_exists(role: str) -> bool:
    """True when `role` is a real Postgres role on this cluster.

    Managed Postgres (Render, Neon, RDS) hands over one owner role and no
    ability to create others, so the GRANTs below have nothing to grant to.
    Guarding every one of them is why this migration runs on both a
    self-hosted cluster with a least-privilege app role and a managed instance
    without one. 0002 shipped without this guard and took a deploy down.
    """
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        .scalar()
    )


def upgrade() -> None:
    # Commands from the owner's screen to the gateway. Timestamps rather than
    # booleans: the gateway claims a command by comparing it to what it has
    # already acted on, and "when was this asked for" is what the audit trail
    # and the UI both want to show.
    op.add_column(
        "whatsapp_session",
        sa.Column("pair_requested_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "whatsapp_session",
        sa.Column("sync_requested_at", sa.DateTime(timezone=True)),
    )
    # When the group list below was last refreshed from WhatsApp, so the picker
    # can say "as of ten minutes ago" instead of implying it is live.
    op.add_column(
        "whatsapp_session",
        sa.Column("directory_synced_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "whatsapp_group_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_jid", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "participants", sa.Integer(), nullable=False, server_default="0"
        ),
        # Groups the account has left stop appearing in the gateway's upload.
        # Keeping the row and ageing it is kinder than deleting: a group that
        # vanishes because a sync ran mid-reconnect comes back on the next one.
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # The picker's only two access patterns: sort by name, and look up by jid to
    # decide whether a candidate is already being watched.
    op.create_index(
        "idx_wa_candidates_name", "whatsapp_group_candidates", ["name"]
    )

    if not _role_exists(APP_ROLE):
        print(f"[0007] role {APP_ROLE!r} not present - skipping GRANT.")
        return
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE whatsapp_group_candidates "
        f"TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("idx_wa_candidates_name", table_name="whatsapp_group_candidates")
    op.drop_table("whatsapp_group_candidates")
    op.drop_column("whatsapp_session", "directory_synced_at")
    op.drop_column("whatsapp_session", "sync_requested_at")
    op.drop_column("whatsapp_session", "pair_requested_at")
