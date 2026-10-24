"""Repeated lockouts: users.lockouts (in a row, for the doubling lock) and users.wrong_pins (since the last login,
shown at the next one) (issue #86)."""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("lockouts", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("wrong_pins", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("wrong_pins")
        batch.drop_column("lockouts")
