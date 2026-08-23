"""Record whether the lead is renting or buying.

The one question that splits the book in half, and the lead record could not
answer it. Inventory has always had to: ``properties.listing_type`` is NOT NULL,
because a listing that does not say whether it is for rent or for sale is not a
listing. Leads had no such column, so the matcher had nothing to compare against
and cheerfully offered a ₹3Cr outright flat to someone looking for a ₹60k
rental -- the budgets are not even in the same units, one being a monthly figure
and the other a purchase price.

Nullable, unlike the inventory side: leads already in the book predate this, and
a blank is honest about not knowing rather than guessing "outright" for six
hundred imported numbers.

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Same vocabulary as properties.listing_type -- 'rent' or 'outright' -- so
    # the lead's answer and the listing's answer compare directly.
    op.add_column("contacts", sa.Column("listing_type_interest", sa.Text()))

    # The leads screen filters on this on top of the is_lead narrowing it always
    # applies, exactly as the size filter does.
    op.create_index(
        "idx_contacts_listing_type", "contacts", ["listing_type_interest", "is_lead"]
    )


def downgrade() -> None:
    op.drop_index("idx_contacts_listing_type", table_name="contacts")
    op.drop_column("contacts", "listing_type_interest")
