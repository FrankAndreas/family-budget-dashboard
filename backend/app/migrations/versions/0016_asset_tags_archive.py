"""Investments get a tag (grouping on the Investments tab) and can be archived (sold, scrapped: out of the totals)."""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("tag_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("archived_on", sa.Date(), nullable=True))
        batch.create_foreign_key("fk_assets_tag_id", "tags", ["tag_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.drop_constraint("fk_assets_tag_id", type_="foreignkey")
        batch.drop_column("archived_on")
        batch.drop_column("tag_id")
