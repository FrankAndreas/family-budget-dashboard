"""The booking that bought an investment: transactions.asset_purchase (one per investment)."""

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("asset_purchase", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("asset_purchase")
