"""Indexes for reading an account's transactions by date, and for finding a reference (import duplicates).

if_not_exists: a database caught up from before migrations already got them from create_all.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_transactions_account_date", "transactions", ["account_id", "date"], if_not_exists=True)
    op.create_index("ix_transactions_reference", "transactions", ["reference"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_transactions_reference", table_name="transactions")
    op.drop_index("ix_transactions_account_date", table_name="transactions")
