"""Record what size the lead wants, and whatever else was said on the call.

Two things agents were keeping in their heads or in WhatsApp:

* **How many bedrooms.** Inventory has carried ``bhk`` since 0001 and the
  properties screen filters on it, but a lead could only say "apartment" — so
  the matcher happily suggested a 1BHK to someone who wants a 3BHK, and the
  leads list could not be narrowed by the single question every buyer answers
  first.

* **Everything the fields don't cover.** "Wants possession before June",
  "husband decides", "seen Lodha Amara, didn't like the layout". This was
  going into call logs, where it is buried under whichever call happened to be
  in progress when it came up, or nowhere at all.

Both are nullable: every lead already in the book predates them, and a blank
``remarks`` is honest about that rather than inventing a value.

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Same type and meaning as properties.bhk, so a lead's stated size and a
    # listing's actual size compare without a translation step. 4 means "4 or
    # more" on both screens.
    op.add_column("contacts", sa.Column("bhk", sa.Integer()))
    op.add_column("contacts", sa.Column("remarks", sa.Text()))

    # The leads list filters on size the same way the inventory list does, and
    # that filter is always combined with the ``is_lead`` narrowing the screen
    # applies first.
    op.create_index("idx_contacts_bhk", "contacts", ["bhk", "is_lead"])


def downgrade() -> None:
    op.drop_index("idx_contacts_bhk", table_name="contacts")
    op.drop_column("contacts", "remarks")
    op.drop_column("contacts", "bhk")
