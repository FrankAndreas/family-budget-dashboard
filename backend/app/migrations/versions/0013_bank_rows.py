"""Reconciliation: imported bank lines (bank_rows), and a booking's receipt/difference flags."""

from alembic import op
import sqlalchemy as sa

from app.money import Money

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_rows",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("account_id", sa.String(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("transaction_id", sa.String(), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("booked_on", sa.Date(), nullable=False),
        sa.Column("valuta_on", sa.Date(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("amount", Money(), nullable=False),
        sa.Column("balance", Money(), nullable=True),
        sa.Column("reference", sa.String(), nullable=False, unique=True),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_bank_rows_account_id", "bank_rows", ["account_id"])
    op.create_index("ix_bank_rows_transaction_id", "bank_rows", ["transaction_id"])
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("receipt_expected", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("difference", Money(), nullable=True))
        batch.add_column(sa.Column("difference_accepted", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("difference_accepted")
        batch.drop_column("difference")
        batch.drop_column("receipt_expected")
    op.drop_table("bank_rows")
