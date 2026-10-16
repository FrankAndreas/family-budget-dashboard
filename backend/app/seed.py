import os
import re
import secrets
from typing import Optional

from sqlalchemy.orm import Session
from . import auth, models

# Fixed keys of the categories the code needs (categories.system_key); their names can't change
TRANSFER = "TRANSFER"
SETTLE_UP = "SETTLE_UP"
UNSORTED = "UNSORTED"
UNKNOWN_EXPENSE = "UNKNOWN_EXPENSE"
OTHER_INCOME = "OTHER_INCOME"

DEFAULT_CATEGORIES = [
    # Income categories
    {"name": "Salary", "type": "INCOME", "icon": "💰"},
    {"name": "Freelance", "type": "INCOME", "icon": "💼"},
    {"name": "Investment", "type": "INCOME", "icon": "📈"},
    {"name": "Gift", "type": "INCOME", "icon": "🎁"},
    # Also the month check's booking when receipts exceed the money, and the income fallback of imports
    {"name": "Other Income", "type": "INCOME", "icon": "💵", "system_key": OTHER_INCOME},
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
    {"name": "Unsorted", "type": "EXPENSE", "icon": "❓", "system_key": UNSORTED},
    {"name": "Reimbursements", "type": "INCOME", "icon": "↩️"},
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
        for cat_data in DEFAULT_CATEGORIES:
            db.add(models.Category(**cat_data, is_global=True))
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
