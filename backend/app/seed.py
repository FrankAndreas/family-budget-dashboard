from sqlalchemy.orm import Session
from . import i18n, models

# Fixed keys of the categories the code needs (categories.system_key); their names can't change
TRANSFER = "TRANSFER"
SETTLE_UP = "SETTLE_UP"
UNSORTED = "UNSORTED"
UNKNOWN_EXPENSE = "UNKNOWN_EXPENSE"
OTHER_INCOME = "OTHER_INCOME"

# Shown in each person's language (i18n.py): the 🔒 ones always, the others (default_key) until a parent renames them
DEFAULT_CATEGORIES = [
    # Income categories
    {"name": "Salary", "default_key": "SALARY", "type": "INCOME", "icon": "💰"},
    {"name": "Freelance", "default_key": "FREELANCE", "type": "INCOME", "icon": "💼"},
    {"name": "Investment", "default_key": "INVESTMENT", "type": "INCOME", "icon": "📈"},
    {"name": "Gift", "default_key": "GIFT", "type": "INCOME", "icon": "🎁"},
    # Also the month check's booking when receipts exceed the money, and the income fallback of imports
    {"name": "Other Income", "type": "INCOME", "icon": "💵", "system_key": OTHER_INCOME},
    # Expense categories
    {"name": "Groceries", "default_key": "GROCERIES", "type": "EXPENSE", "icon": "🛒"},
    {"name": "Rent", "default_key": "RENT", "type": "EXPENSE", "icon": "🏠"},
    {"name": "Utilities", "default_key": "UTILITIES", "type": "EXPENSE", "icon": "💡"},
    {"name": "Transportation", "default_key": "TRANSPORTATION", "type": "EXPENSE", "icon": "🚗"},
    {"name": "Entertainment", "default_key": "ENTERTAINMENT", "type": "EXPENSE", "icon": "🎬"},
    {"name": "Healthcare", "default_key": "HEALTHCARE", "type": "EXPENSE", "icon": "🏥"},
    {"name": "Education", "default_key": "EDUCATION", "type": "EXPENSE", "icon": "📚"},
    {"name": "Clothing", "default_key": "CLOTHING", "type": "EXPENSE", "icon": "👕"},
    {"name": "Dining Out", "default_key": "DINING_OUT", "type": "EXPENSE", "icon": "🍽️"},
    {"name": "Other Expense", "default_key": "OTHER_EXPENSE", "type": "EXPENSE", "icon": "💸"},
    {"name": "Sport", "default_key": "SPORT", "type": "EXPENSE", "icon": "🏅"},
    {"name": "Communication", "default_key": "COMMUNICATION", "type": "EXPENSE", "icon": "📡"},
    # Fallbacks for imported bookings no rule recognised, and money paid back by others
    {"name": "Unsorted", "type": "EXPENSE", "icon": "❓", "system_key": UNSORTED},
    {"name": "Reimbursements", "default_key": "REIMBURSEMENTS", "type": "INCOME", "icon": "↩️"},
    # The month check's booking for money on a clearing account without receipts
    {"name": "Unknown expense", "type": "EXPENSE", "icon": "🫥", "system_key": UNKNOWN_EXPENSE},
    # Booked only by settling up in the common budget
    {"name": "Settle up", "type": "TRANSFER", "icon": "🔁", "system_key": SETTLE_UP},
    # Money moved between the family's own accounts (imported); counts as neither income nor expense
    {"name": "Transfer", "type": "TRANSFER", "icon": "↔️", "system_key": TRANSFER},
]


def seed_categories(db: Session) -> int:
    """A new database gets all default categories; afterwards only the system categories are ensured (by key), so
    a renamed or deleted default doesn't come back. Returns how many were created."""
    created = 0
    if db.query(models.Category).count() == 0:
        german = i18n.default_language() == "de"
        for cat_data in DEFAULT_CATEGORIES:
            columns = dict(cat_data)
            # A new German install stores the German name (shown when a category loses its key by a rename)
            if german and cat_data.get("default_key"):
                columns["name"] = i18n.DEFAULT_NAMES[cat_data["default_key"]]["de"]
            db.add(models.Category(**columns, is_global=True))
        created = len(DEFAULT_CATEGORIES)
    else:
        for cat_data in (c for c in DEFAULT_CATEGORIES if c.get("system_key")):
            if db.query(models.Category).filter(models.Category.system_key == cat_data["system_key"]).first():
                continue
            same_name = db.query(models.Category).filter(models.Category.name == cat_data["name"]).first()
            if same_name:
                same_name.system_key = cat_data["system_key"]
            else:
                db.add(models.Category(**cat_data, is_global=True))
                created += 1
    db.commit()
    return created


def system_category(db: Session, key: str) -> models.Category:
    """One of the categories the code needs, by its fixed key (see seed_categories)."""
    return db.query(models.Category).filter(models.Category.system_key == key).one()
