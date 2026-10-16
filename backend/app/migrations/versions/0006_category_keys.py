"""Fixed keys for the categories the code needs (categories.system_key), so other categories can be renamed."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

KEYS = {
    "Transfer": "TRANSFER",
    "Settle up": "SETTLE_UP",
    "Unsorted": "UNSORTED",
    "Unknown expense": "UNKNOWN_EXPENSE",
    "Other Income": "OTHER_INCOME",
}


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch:
        batch.add_column(sa.Column("system_key", sa.String(), nullable=True))
        batch.create_index("ix_categories_system_key", ["system_key"], unique=True)
    for name, key in KEYS.items():
        op.execute(sa.text("UPDATE categories SET system_key = :key WHERE name = :name").bindparams(key=key, name=name))


def downgrade() -> None:
    with op.batch_alter_table("categories") as batch:
        batch.drop_index("ix_categories_system_key")
        batch.drop_column("system_key")
