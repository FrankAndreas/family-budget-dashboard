"""Baseline: the schema as it was when migrations were introduced (2026-10-16).

Every table is created only if it's missing: a database from before migrations already has most of them
(its missing columns are added first, in app/database_setup.py), and gets the rest here.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def create_table(name, *columns):
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns)


def upgrade() -> None:
    create_table(
        "categories",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("type", sa.Enum("INCOME", "EXPENSE", "TRANSFER", name="categorytype"), nullable=True),
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    create_table(
        "splits",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("shares", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("pin_hash", sa.String(), nullable=True),
        sa.Column("role", sa.Enum("PARENT", "CHILD", name="userrole"), nullable=True),
        sa.Column("has_allowance", sa.Boolean(), nullable=True),
        sa.Column("privacy_enabled", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True, if_not_exists=True)

    create_table(
        "accounts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("type", sa.Enum("CASH", "BANK", "SAVINGS", "CLEARING", name="accounttype"), nullable=True),
        sa.Column("balance", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    create_table(
        "assets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("lifespan_years", sa.Integer(), nullable=True),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("split_id", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["split_id"],
            ["splits.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    create_table(
        "budgets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("category_id", sa.String(), nullable=True),
        sa.Column("limit", sa.Float(), nullable=True),
        sa.Column("period", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    create_table(
        "import_rules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=True),
        sa.Column("category_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    create_table(
        "planned_costs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("category_id", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("frequency", sa.Enum("MONTHLY", "YEARLY", name="frequency"), nullable=True),
        sa.Column("due_month", sa.Integer(), nullable=True),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("split_id", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["split_id"],
            ["splits.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    create_table(
        "shares",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("grantee_id", sa.String(), nullable=True),
        sa.Column("level", sa.Enum("NONE", "VIEW", "EDIT", name="sharelevel"), nullable=True),
        sa.ForeignKeyConstraint(
            ["grantee_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    create_table(
        "wishes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("estimate", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("split_id", sa.String(), nullable=True),
        sa.Column("best_price", sa.Float(), nullable=True),
        sa.Column("best_shop", sa.String(), nullable=True),
        sa.Column("best_url", sa.String(), nullable=True),
        sa.Column("best_checked", sa.Date(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("family_position", sa.Integer(), nullable=True),
        sa.Column("bought_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["split_id"],
            ["splits.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    create_table(
        "transactions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("category_id", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("member_id", sa.String(), nullable=True),
        sa.Column("split_id", sa.String(), nullable=True),
        sa.Column("split_shares", sa.JSON(), nullable=True),
        sa.Column("asset_id", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["split_id"],
            ["splits.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    create_table(
        "settlements",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("from_user_id", sa.String(), nullable=True),
        sa.Column("to_user_id", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=True),
        sa.Column("from_transaction_id", sa.String(), nullable=True),
        sa.Column("to_transaction_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["from_transaction_id"],
            ["transactions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["from_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["to_transaction_id"],
            ["transactions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["to_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("settlements")
    op.drop_table("transactions")
    op.drop_table("wishes")
    op.drop_table("shares")
    op.drop_table("planned_costs")
    op.drop_table("import_rules")
    op.drop_table("budgets")
    op.drop_table("assets")
    op.drop_table("accounts")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_username"))

    op.drop_table("users")
    op.drop_table("splits")
    op.drop_table("categories")
