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


def system_name(system_key: Optional[str], stored: str) -> str:
    """The name to show: a 🔒 category's in the request's language, any other its stored one."""
    names = SYSTEM_NAMES.get(system_key or "")
    return names[current()] if names else stored


def category_name(category: "models.Category") -> str:
    return system_name(category.system_key, category.name)


def all_names(category: "models.Category") -> set[str]:
    """Every name an import file may use for the category (and that no other category may take)."""
    return {category.name, *SYSTEM_NAMES.get(category.system_key or "", {}).values()}


async def language_from_header(request: Request) -> None:
    """App-wide dependency: every request starts in the browser's language (or the default)."""
    set_current(from_header(request.headers.get("accept-language")))
