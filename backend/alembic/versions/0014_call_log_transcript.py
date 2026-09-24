"""Keep the transcript of an uploaded call recording on its call log.

Additive and nullable: every existing call and every typed remark is
unaffected. The audio is never stored, only this text.

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_logs", sa.Column("transcript", sa.Text()))


def downgrade() -> None:
    op.drop_column("call_logs", "transcript")
