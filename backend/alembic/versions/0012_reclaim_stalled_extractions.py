"""Stop messages disappearing into "extracting" for ever.

Claiming a message sets its status to `processing`. Nothing ever set it back.
If the worker died between the claim and the result -- and on Render's free
plan, where the extraction loop runs inside an API that suspends after about
fifteen minutes of inactivity, it dies that way several times a day -- the row
was stranded: `claim_pending` only ever looks at `pending`, and the owner's
"retry failed" only ever looks at `failed`. A `processing` row was reachable by
neither, so the feed showed messages stuck on "Extracting" with no way back.

Reclaiming needs to know *when* the claim happened, which nothing recorded --
`received_at` is when the message arrived and says nothing about the worker.
Hence this column.

Existing `processing` rows are backfilled to the epoch rather than to now(),
so the ones stranded by this bug are reclaimed on the first pass after deploy
instead of waiting out a timeout that never applied to them.

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_messages", sa.Column("claimed_at", sa.DateTime(timezone=True))
    )
    # Anything already stuck has been stuck for a while by definition.
    op.execute(
        "UPDATE whatsapp_messages SET claimed_at = TIMESTAMPTZ 'epoch' "
        "WHERE status = 'processing'"
    )
    # The reclaim query: stalled rows only, and there are never many, so a
    # partial index keeps it off the far larger set of finished messages.
    op.create_index(
        "idx_whatsapp_messages_claimed",
        "whatsapp_messages",
        ["claimed_at"],
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index("idx_whatsapp_messages_claimed", table_name="whatsapp_messages")
    op.drop_column("whatsapp_messages", "claimed_at")
