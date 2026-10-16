"""Repair links: clear a transaction's optional links (child, split, investment) that point nowhere.

Before foreign keys were enforced, deleting a split left shared expenses pointing to it. Nothing is deleted here;
a shared expense stays shared through the percentages it was booked with (split_shares).
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OPTIONAL_LINKS = {"member_id": "users", "split_id": "splits", "asset_id": "assets"}


def upgrade() -> None:
    for column, parent in OPTIONAL_LINKS.items():
        op.execute(
            f"UPDATE transactions SET {column} = NULL "
            f"WHERE {column} IS NOT NULL AND {column} NOT IN (SELECT id FROM {parent})"
        )


def downgrade() -> None:
    # The broken links aren't worth restoring
    pass
