"""AI receipt reads in the database, so the hourly limit survives a restart (issue #59)."""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receipt_reads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_receipt_reads_user_id", "receipt_reads", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_receipt_reads_user_id", "receipt_reads")
    op.drop_table("receipt_reads")
