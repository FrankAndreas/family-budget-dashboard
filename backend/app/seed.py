from sqlalchemy.orm import Session
from . import models

DEFAULT_CATEGORIES = [
    # Income categories
    {"name": "Salary", "type": "INCOME", "icon": "💰"},
    {"name": "Freelance", "type": "INCOME", "icon": "💼"},
    {"name": "Investment", "type": "INCOME", "icon": "📈"},
    {"name": "Gift", "type": "INCOME", "icon": "🎁"},
    {"name": "Other Income", "type": "INCOME", "icon": "💵"},
    # Expense categories
    {"name": "Groceries", "type": "EXPENSE", "icon": "🛒"},
    {"name": "Rent", "type": "EXPENSE", "icon": "🏠"},
    {"name": "Utilities", "type": "EXPENSE", "icon": "💡"},
    {"name": "Transportation", "type": "EXPENSE", "icon": "🚗"},
    {"name": "Entertainment", "type": "EXPENSE", "icon": "🎬"},
    {"name": "Healthcare", "type": "EXPENSE", "icon": "🏥"},
    {"name": "Education", "type": "EXPENSE", "icon": "📚"},
    {"name": "Clothing", "type": "EXPENSE", "icon": "👕"},
    {"name": "Dining Out", "type": "EXPENSE", "icon": "🍽️"},
    {"name": "Other Expense", "type": "EXPENSE", "icon": "💸"},
]


def seed_categories(db: Session) -> int:
    """Create the default categories if the table is empty. Returns how many were created."""
    if db.query(models.Category).count() > 0:
        return 0

    for cat_data in DEFAULT_CATEGORIES:
        db.add(models.Category(**cat_data, is_global=True))
    db.commit()
    return len(DEFAULT_CATEGORIES)
