"""Error messages in German and English (issue #50).

Endpoints raise api_error(status, key, **params); the text comes in the request's language (see i18n.py).
Texts with a number have two keys, <key>_one and <key>_other, picked by plural().
German: Swiss spelling (ss, never ß), informal "du".
"""

from typing import Optional

from fastapi import HTTPException

from . import i18n

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "not_logged_in": "Could not validate credentials",
        "wrong_login": "Incorrect username or PIN",
        "login_locked_one": "Too many wrong PINs. Try again in {count} minute.",
        "login_locked_other": "Too many wrong PINs. Try again in {count} minutes.",
        "category_not_found": "Category not found",
    },
    "de": {
        "not_logged_in": "Anmeldung ungültig, bitte melde dich neu an",
        "wrong_login": "Benutzername oder PIN falsch",
        "login_locked_one": "Zu viele falsche PINs. Versuche es in {count} Minute wieder.",
        "login_locked_other": "Zu viele falsche PINs. Versuche es in {count} Minuten wieder.",
        "category_not_found": "Kategorie nicht gefunden",
    },
}


def text(key: str, **params) -> str:
    return MESSAGES[i18n.current()][key].format(**params)


def plural(key: str, count: int, **params) -> str:
    return text(f"{key}_one" if count == 1 else f"{key}_other", count=count, **params)


def api_error(status_code: int, key: str, headers: Optional[dict] = None, **params) -> HTTPException:
    return HTTPException(status_code=status_code, detail=text(key, **params), headers=headers)
