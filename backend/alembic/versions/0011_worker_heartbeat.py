"""Let the feed say "nothing is extracting" instead of implying it.

The Inventory feed could report two things about extraction: whether a model
key was configured, and how many messages were queued. Neither answers the
question an owner actually has when inventory stops appearing -- *is anything
running?* -- so the screen guessed, with a banner that fired at twenty queued
messages and said the worker "may not be running".

It was a guess because nothing recorded the fact. The extraction loop can live
in three places (its own Render service, a thread inside the API, a terminal on
someone's laptop) and the API has no way to see the first or the third. So the
loop writes down that it is alive, and the screen reads it back.

One row per worker name, upserted on every pass through the loop. Not a log:
nothing here is worth keeping historically, and a table that grows a row every
five seconds forever would be its own problem.

Deliberately not added to ``db.GUARDED_MAPPERS``. Everything guarded there is
data belonging to a person -- contacts, calls, messages -- where the question
"whose is this?" has an answer that must be enforced in SQL. A heartbeat has no
owner and reveals nothing about the firm's book, so requiring a role filter on
it would be ceremony rather than a control.

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

APP_ROLE = "balaji_app"


def _role_exists(role: str) -> bool:
    """True when `role` is a real Postgres role on this cluster.

    Local development runs two roles -- a migrator that owns the tables and an
    app role with no DDL rights -- while managed Postgres hands out one owner
    role and nothing else. An unguarded GRANT aborts the deploy there with
    `role "balaji_app" does not exist`.
    """
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        .scalar()
    )


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        # The worker's name, not a serial id: there is exactly one row per kind
        # of worker and the writer knows its own name, so an upsert needs no
        # prior read to find out which row is its own.
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Free text for whatever helps identify *which* process this is when
        # two of them disagree -- host, pid, "in-api" vs "standalone".
        sa.Column("note", sa.Text()),
    )

    # The app role writes this beat when the extraction loop runs inside the
    # API process, and reads it for the feed screen. Without the grant that
    # deployment -- the free-plan one, where this diagnostic matters most --
    # fails on permission denied.
    if not _role_exists(APP_ROLE):
        print(f"[0011] role {APP_ROLE!r} not present - skipping GRANT.")
        return
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE worker_heartbeats TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
