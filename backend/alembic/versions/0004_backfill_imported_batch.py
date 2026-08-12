"""Move already-imported numbers out of the leads pipeline.

0003 introduced the distinction between a call target and a lead but left every
existing row a lead, which was the safe default for a schema change. This
migration applies the distinction retroactively to the rows that were only ever
spreadsheet imports, so the leads screen stops showing hundreds of people nobody
has spoken to.

Two predicates, both deliberately narrow:

  * ``lead_source = 'imported_list'`` — the value the bulk importer stamps and
    nothing else sets. A walk-in or a portal enquiry is a lead the moment it
    arrives and is left alone.
  * ``stage = 'new'`` — nobody has moved it. A number that has been called and
    advanced has already been judged worth keeping by a human, and demoting it
    would throw that judgement away.

Rows are gathered under one batch rather than left unattributed. The original
filenames are gone, so the batch is named for what it honestly is; the point is
that these numbers now have somewhere to be counted rather than a precise
provenance this migration cannot reconstruct.

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

LEGACY_NAME = "Imported list (before batch tracking)"


def upgrade() -> None:
    bind = op.get_bind()

    affected = bind.execute(
        sa.text(
            "SELECT count(*) FROM contacts "
            "WHERE deleted_at IS NULL AND batch_id IS NULL "
            "AND lead_source = 'imported_list' AND stage = 'new'"
        )
    ).scalar_one()
    if not affected:
        return

    # Attributed to no one: the uploader is not recoverable, and guessing at the
    # owner would put a name against an import they may not have run.
    batch_id = bind.execute(
        sa.text(
            "INSERT INTO lead_batches "
            "  (name, source_filename, total_rows, imported_rows, "
            "   duplicate_rows, invalid_rows) "
            "VALUES (:name, NULL, :n, :n, 0, 0) RETURNING id"
        ),
        {"name": LEGACY_NAME, "n": affected},
    ).scalar_one()

    bind.execute(
        sa.text(
            "UPDATE contacts SET batch_id = :b, is_lead = false "
            "WHERE deleted_at IS NULL AND batch_id IS NULL "
            "AND lead_source = 'imported_list' AND stage = 'new'"
        ),
        {"b": batch_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE contacts SET is_lead = true, batch_id = NULL "
            "WHERE batch_id IN (SELECT id FROM lead_batches WHERE name = :name)"
        ),
        {"name": LEGACY_NAME},
    )
    bind.execute(
        sa.text("DELETE FROM lead_batches WHERE name = :name"), {"name": LEGACY_NAME}
    )
