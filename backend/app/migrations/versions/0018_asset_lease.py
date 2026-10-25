"""Leased investments: assets.kind (PURCHASE or LEASE) and the lease's rate, term (months) and final payment."""

from alembic import op
import sqlalchemy as sa

from app.money import Money

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("kind", sa.String(), nullable=False, server_default="PURCHASE"))
        batch.add_column(sa.Column("lease_rate", Money(), nullable=True))
        batch.add_column(sa.Column("lease_months", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("lease_final", Money(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.drop_column("lease_final")
        batch.drop_column("lease_months")
        batch.drop_column("lease_rate")
        batch.drop_column("kind")
