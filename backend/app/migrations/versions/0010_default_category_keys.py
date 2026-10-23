"""Keys for the untouched default categories, so they show in each person's language (categories.default_key).

A category gets its key when it still has the default's English or German name. If both names exist (a family
added the other one themselves), neither gets it and both keep their stored names.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# A copy of i18n.DEFAULT_NAMES as of this migration
NAMES = {
    "SALARY": ("Salary", "Lohn"),
    "FREELANCE": ("Freelance", "Nebenerwerb"),
    "INVESTMENT": ("Investment", "Kapitalertrag"),
    "GIFT": ("Gift", "Geschenk"),
    "GROCERIES": ("Groceries", "Lebensmittel"),
    "RENT": ("Rent", "Miete"),
    "UTILITIES": ("Utilities", "Nebenkosten"),
    "TRANSPORTATION": ("Transportation", "Mobilität"),
    "ENTERTAINMENT": ("Entertainment", "Freizeit"),
    "HEALTHCARE": ("Healthcare", "Gesundheit"),
    "EDUCATION": ("Education", "Bildung"),
    "CLOTHING": ("Clothing", "Kleidung"),
    "DINING_OUT": ("Dining Out", "Auswärts essen"),
    "OTHER_EXPENSE": ("Other Expense", "Übrige Ausgaben"),
    "REIMBURSEMENTS": ("Reimbursements", "Rückerstattungen"),
}


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch:
        batch.add_column(sa.Column("default_key", sa.String(), nullable=True))
        batch.create_index("ix_categories_default_key", ["default_key"], unique=True)
    conn = op.get_bind()
    for key, (english, german) in NAMES.items():
        ids = conn.execute(
            sa.text("SELECT id FROM categories WHERE system_key IS NULL AND name IN (:en, :de)"),
            {"en": english, "de": german},
        ).all()
        if len(ids) == 1:
            conn.execute(
                sa.text("UPDATE categories SET default_key = :key WHERE id = :id"), {"key": key, "id": ids[0].id}
            )


def downgrade() -> None:
    with op.batch_alter_table("categories") as batch:
        batch.drop_index("ix_categories_default_key")
        batch.drop_column("default_key")
