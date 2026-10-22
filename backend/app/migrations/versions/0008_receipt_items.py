"""Receipt items, tags, attachments, and budgets per tag (issue #56)."""

from alembic import op
import sqlalchemy as sa

from app.money import Money

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("icon", sa.String(), nullable=True),
    )
    op.create_table(
        "transaction_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("transaction_id", sa.String(), sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("amount", Money(), nullable=False),
        sa.Column("category_id", sa.String(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("person_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_transaction_items_transaction_id", "transaction_items", ["transaction_id"])
    op.create_table(
        "transaction_item_tags",
        sa.Column("item_id", sa.String(), sa.ForeignKey("transaction_items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.String(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("transaction_id", sa.String(), sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_attachments_transaction_id", "attachments", ["transaction_id"])
    with op.batch_alter_table("budgets") as batch:
        batch.add_column(sa.Column("tag_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_budgets_tag_id_tags", "tags", ["tag_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("budgets") as batch:
        batch.drop_constraint("fk_budgets_tag_id_tags", type_="foreignkey")
        batch.drop_column("tag_id")
    op.drop_index("ix_attachments_transaction_id", "attachments")
    op.drop_table("attachments")
    op.drop_table("transaction_item_tags")
    op.drop_index("ix_transaction_items_transaction_id", "transaction_items")
    op.drop_table("transaction_items")
    op.drop_table("tags")
