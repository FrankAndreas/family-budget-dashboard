"""Money in integer cents: every amount column becomes INTEGER cents (the code and API keep francs via the Money
type), and the unused accounts.balance goes (balances are calculated since 0003's release).

Batch mode rebuilds each table; app/database_setup.py runs migrations with link checking off for that, as SQLite's
documentation prescribes for table rebuilds.
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

MONEY = {
    "transactions": ["amount"],
    "budgets": ["limit"],
    "assets": ["price"],
    "settlements": ["amount"],
    "planned_costs": ["amount"],
    "wishes": ["estimate", "best_price"],
}


def upgrade() -> None:
    for table, columns in MONEY.items():
        for column in columns:
            op.execute(
                f'UPDATE {table} SET "{column}" = CAST(ROUND("{column}" * 100) AS INTEGER) '
                f'WHERE "{column}" IS NOT NULL'
            )
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(column, type_=sa.Integer(), existing_type=sa.Float())
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("balance")


def downgrade() -> None:
    for table, columns in MONEY.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(column, type_=sa.Float(), existing_type=sa.Integer())
        for column in columns:
            op.execute(f'UPDATE {table} SET "{column}" = "{column}" / 100.0 WHERE "{column}" IS NOT NULL')
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("balance", sa.Float(), nullable=True))
    op.execute(
        "UPDATE accounts SET balance = "
        "(SELECT ROUND(COALESCE(SUM(amount), 0), 2) FROM transactions WHERE transactions.account_id = accounts.id)"
    )
