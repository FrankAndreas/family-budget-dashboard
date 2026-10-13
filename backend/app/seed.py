import os
import re
import secrets
from typing import Optional

from sqlalchemy.orm import Session
from . import auth, models

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


def seed_admin(db: Session) -> Optional[str]:
    """On an empty database, create the first parent ("Admin") with a 4-digit PIN.

    The PIN is random unless INITIAL_ADMIN_PIN is set (used by CI). Returns the PIN so it can be
    shown once, or None if there are already users.
    """
    if db.query(models.User).count() > 0:
        return None

    pin = os.getenv("INITIAL_ADMIN_PIN") or f"{secrets.randbelow(10000):04d}"
    if not re.fullmatch(r"\d{4}", pin):
        raise ValueError("INITIAL_ADMIN_PIN must be exactly 4 digits")
    db.add(
        models.User(
            username="Admin",
            pin_hash=auth.get_pin_hash(pin),
            role=models.UserRole.PARENT,
            has_allowance=True,
        )
    )
    db.commit()
    return pin
