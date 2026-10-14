import os
import re
import secrets
from typing import Optional

from sqlalchemy.orm import Session
from . import auth, models

SETTLE_UP = "Settle up"
TRANSFER = "Transfer"

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
    # Fallbacks for imported bookings no rule recognised, and money paid back by others
    {"name": "Unsorted", "type": "EXPENSE", "icon": "❓"},
    {"name": "Reimbursements", "type": "INCOME", "icon": "↩️"},
    # Booked only by settling up in the common budget
    {"name": SETTLE_UP, "type": "TRANSFER", "icon": "🔁"},
    # Money moved between the family's own accounts (imported); counts as neither income nor expense
    {"name": TRANSFER, "type": "TRANSFER", "icon": "↔️"},
]


def seed_categories(db: Session) -> int:
    """Create the default categories that don't exist yet (by name). Returns how many were created."""
    existing = {name for (name,) in db.query(models.Category.name)}
    missing = [cat for cat in DEFAULT_CATEGORIES if cat["name"] not in existing]
    for cat_data in missing:
        db.add(models.Category(**cat_data, is_global=True))
    db.commit()
    return len(missing)


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
