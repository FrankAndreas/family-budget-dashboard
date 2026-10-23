"""The language of a request (issue #50): German or English.

A person's own setting (users.settings["language"]) once their login is checked; before that, the browser's
Accept-Language; otherwise DEFAULT_LANGUAGE (environment, German if unset). The language lives in a context
variable for the request, so error messages and category names can be translated without passing it around.
"""

import os
from contextvars import ContextVar
from typing import TYPE_CHECKING, Optional

from fastapi import Request

if TYPE_CHECKING:
    from . import models

LANGUAGES = ("de", "en")

_current: ContextVar[Optional[str]] = ContextVar("language", default=None)


def default_language() -> str:
    configured = os.environ.get("DEFAULT_LANGUAGE", "de")
    return configured if configured in LANGUAGES else "de"


def current() -> str:
    return _current.get() or default_language()


def set_current(lang: Optional[str]) -> None:
    _current.set(lang)


def from_header(value: Optional[str]) -> Optional[str]:
    """The supported language the browser prefers most: "de-CH,de;q=0.9,en;q=0.8" -> "de"."""
    choices = []
    for position, part in enumerate((value or "").split(",")):
        tag, _, params = part.strip().partition(";")
        weight = 1.0
        if params.strip().startswith("q="):
            try:
                weight = float(params.strip()[2:])
            except ValueError:
                continue
        lang = tag.strip().split("-")[0].lower()
        if lang in LANGUAGES:
            choices.append((-weight, position, lang))
    return min(choices)[2] if choices else None


def user_language(user: "models.User") -> str:
    stored = (user.settings or {}).get("language")
    return stored if stored in LANGUAGES else default_language()


# The 🔒 categories by system_key; the English name is the one stored in the database
SYSTEM_NAMES = {
    "UNSORTED": {"en": "Unsorted", "de": "Unsortiert"},
    "UNKNOWN_EXPENSE": {"en": "Unknown expense", "de": "Unbekannte Ausgabe"},
    "OTHER_INCOME": {"en": "Other Income", "de": "Übrige Einnahmen"},
    "SETTLE_UP": {"en": "Settle up", "de": "Ausgleich"},
    "TRANSFER": {"en": "Transfer", "de": "Umbuchung"},
}


# The default categories by categories.default_key, shown in each person's language until a parent renames them
DEFAULT_NAMES = {
    "SALARY": {"en": "Salary", "de": "Lohn"},
    "FREELANCE": {"en": "Freelance", "de": "Nebenerwerb"},
    "INVESTMENT": {"en": "Investment", "de": "Kapitalertrag"},
    "GIFT": {"en": "Gift", "de": "Geschenk"},
    "GROCERIES": {"en": "Groceries", "de": "Lebensmittel"},
    "RENT": {"en": "Rent", "de": "Miete"},
    "UTILITIES": {"en": "Utilities", "de": "Nebenkosten"},
    "TRANSPORTATION": {"en": "Transportation", "de": "Mobilität"},
    "ENTERTAINMENT": {"en": "Entertainment", "de": "Freizeit"},
    "HEALTHCARE": {"en": "Healthcare", "de": "Gesundheit"},
    "EDUCATION": {"en": "Education", "de": "Bildung"},
    "CLOTHING": {"en": "Clothing", "de": "Kleidung"},
    "DINING_OUT": {"en": "Dining Out", "de": "Auswärts essen"},
    "OTHER_EXPENSE": {"en": "Other Expense", "de": "Übrige Ausgaben"},
    "REIMBURSEMENTS": {"en": "Reimbursements", "de": "Rückerstattungen"},
    "SPORT": {"en": "Sport", "de": "Sport"},
    "COMMUNICATION": {"en": "Communication", "de": "Kommunikation"},
}

NAMES = {**SYSTEM_NAMES, **DEFAULT_NAMES}


def system_name(key: Optional[str], stored: str) -> str:
    """The name to show: a 🔒 or untouched default category's in the request's language, any other its stored one."""
    names = NAMES.get(key or "")
    return names[current()] if names else stored


def name_key(category: "models.Category") -> Optional[str]:
    return category.system_key or category.default_key


def category_name(category: "models.Category") -> str:
    return system_name(name_key(category), category.name)


def all_names(category: "models.Category") -> set[str]:
    """Every name an import file may use for the category (and that no other category may take)."""
    return {category.name, *NAMES.get(name_key(category) or "", {}).values()}


async def language_from_header(request: Request) -> None:
    """App-wide dependency: every request starts in the browser's language (or the default)."""
    set_current(from_header(request.headers.get("accept-language")))
