"""Investments get any number of tags (a bike: Mobility and Bike): assets.tag_id becomes the asset_tags table."""

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_tags",
        sa.Column("asset_id", sa.String(), sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.String(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.execute("INSERT INTO asset_tags (asset_id, tag_id) SELECT id, tag_id FROM assets WHERE tag_id IS NOT NULL")
    with op.batch_alter_table("assets") as batch:
        batch.drop_constraint("fk_assets_tag_id", type_="foreignkey")
        batch.drop_column("tag_id")


def downgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("tag_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_assets_tag_id", "tags", ["tag_id"], ["id"], ondelete="SET NULL")
    # One tag only: the first by name
    op.execute(
        "UPDATE assets SET tag_id = (SELECT asset_tags.tag_id FROM asset_tags JOIN tags ON tags.id = asset_tags.tag_id "
        "WHERE asset_tags.asset_id = assets.id ORDER BY tags.name LIMIT 1)"
    )
    op.drop_table("asset_tags")
