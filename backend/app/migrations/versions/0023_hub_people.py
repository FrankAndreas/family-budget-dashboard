"""People come from the family hub: each row's hub person id (spec 2026-10-30)."""

from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("hub_id", sa.Integer(), nullable=True))
        batch.create_index("ix_users_hub_id", ["hub_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_hub_id")
        batch.drop_column("hub_id")
