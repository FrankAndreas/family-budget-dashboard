"""Receipt mails by forwarding (issue #57): the persons' e-mail addresses and the inbox."""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_emails",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("address", sa.String(), nullable=False, unique=True),
    )
    op.create_index("ix_user_emails_user_id", "user_emails", ["user_id"])
    op.create_table(
        "inbox_mails",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("person_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("from_addr", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False, unique=True),
        sa.Column("attachment_names", sa.JSON(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("attachment_id", sa.String(), sa.ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("booked_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("inbox_mails")
    op.drop_index("ix_user_emails_user_id", "user_emails")
    op.drop_table("user_emails")
