"""Receipts photographed on the phone wait in the inbox (receipt scan)."""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_photos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("person_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("read_state", sa.String(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=True),
        sa.Column("booked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_inbox_photos_sha256", "inbox_photos", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_inbox_photos_sha256", "inbox_photos")
    op.drop_table("inbox_photos")
