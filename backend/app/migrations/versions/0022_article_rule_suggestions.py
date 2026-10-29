"""Article rule suggestions: bookings propose rules, parents add or ignore them (spec 2026-10-29)."""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_rule_suggestions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False, unique=True),
        sa.Column("category_id", sa.String(), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "article_rule_suggestion_tags",
        sa.Column(
            "suggestion_id",
            sa.String(),
            sa.ForeignKey("article_rule_suggestions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tag_id", sa.String(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("article_rule_suggestion_tags")
    op.drop_table("article_rule_suggestions")
