"""Stop signing people out while they are still using the app.

A session was a twelve-hour JWT with nothing behind it. There was no way to
extend one, so every agent signed in again each morning whether or not they had
put the phone down -- and twelve hours is short enough that it also caught
people mid-afternoon. "Stay signed in" and "sessions do not live forever" were
in direct conflict because the only knob was a single fixed lifetime.

Two columns turn that one knob into two independent ones:

* ``chain_started_at`` is when the person actually typed their password. It is
  copied forward every time a token is renewed, so no amount of renewing can
  extend a session past the absolute cap. Without it, a sliding session slides
  indefinitely and a token stolen once is a permanent credential.

* ``last_used_at`` is when the session was last renewed. It is what makes an
  "active sessions" list answerable -- which device, when it was last seen --
  and it is the field the owner would look at before revoking one.

Existing rows are backfilled from ``issued_at``: for a session that has never
been renewed, the moment it was issued *is* the moment the chain started.

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions", sa.Column("chain_started_at", sa.DateTime(timezone=True))
    )
    op.add_column("sessions", sa.Column("last_used_at", sa.DateTime(timezone=True)))

    # A session that has never been renewed started its chain when it was
    # issued. Backfilling rather than defaulting to now() matters: now() would
    # hand every live session a fresh 90 days at deploy time.
    op.execute(
        "UPDATE sessions SET chain_started_at = issued_at "
        "WHERE chain_started_at IS NULL"
    )
    op.alter_column("sessions", "chain_started_at", nullable=False)

    # Renewal looks a session up by jti and checks it is neither revoked nor
    # past its cap. The unique index on jti already serves the lookup; this one
    # serves the owner's "who is signed in right now" question.
    op.create_index(
        "idx_sessions_live", "sessions", ["user_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_sessions_live", table_name="sessions")
    op.drop_column("sessions", "last_used_at")
    op.drop_column("sessions", "chain_started_at")
