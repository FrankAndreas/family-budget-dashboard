"""Bank import: accounts carry an IBAN (unique), import rules can expect a receipt."""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("iban", sa.String(), nullable=True))
        batch.create_index("ix_accounts_iban", ["iban"], unique=True)
    with op.batch_alter_table("import_rules") as batch:
        batch.add_column(sa.Column("receipt_expected", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("import_rules") as batch:
        batch.drop_column("receipt_expected")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_index("ix_accounts_iban")
        batch.drop_column("iban")
