# German and English Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every person uses the app in German or English (their own setting, German by default): frontend texts,
backend error messages and the 🔒 system category names.

**Architecture:** The backend keeps the request's language in a context variable (set from `Accept-Language` by an
app-wide dependency, then from the person's setting once the login token is checked); error messages come from a
catalog in `app/messages.py`, and 🔒 categories get their display name from `app/i18n.py`. The frontend uses
`react-i18next` with type-checked locale files; a node script in the lint step fails on visible text left outside
the locale files.

**Tech Stack:** FastAPI, SQLAlchemy 2, Pydantic 2, pytest; React 19, TypeScript 5.9, i18next 26.4.2,
react-i18next 17.0.15; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-16-german-english-design.md`

## Global Constraints

- Languages: exactly `de` and `en`. `DEFAULT_LANGUAGE` env var, `de` if unset or unsupported.
- Stored per person in `users.settings["language"]`; **no migration**.
- 🔒 categories keep their English name in the database; export ZIP, CSV columns, JSON Schema (`enum`,
  `x-category-types`, `x-rules`), `converter.toml` blocks and log messages stay English.
- Amounts stay `CHF 1'234.50` in both languages (`money()` unchanged).
- Dates: German `16.10.2026` / `Oktober 2026`; English `16 Oct 2026` / `October 2026`.
- German texts: Swiss spelling (**ss, never ß**), informal **du**, short like the English ones.
- Glossary (use consistently): Account = Konto, Booking/transaction = Buchung, Category = Kategorie, Budget = Budget,
  Common (budget) = Gemeinsam / gemeinsames Budget, Split = Aufteilung, Settle up = Ausgleich, Transfer = Umbuchung,
  Yearly bills = Jahresrechnungen, Monthly costs = Monatliche Kosten, Investments = Anschaffungen, Wishes = Wünsche,
  Analytics = Auswertungen, Settings = Einstellungen, Month check = Monatskontrolle, Clearing account =
  Verrechnungskonto, Import rules = Importregeln, Logins = Anmeldungen, Log out = Abmelden, Log out everywhere =
  Überall abmelden, Parent = Elternteil, Child = Kind, Allowance = Jugendlohn, Family = Familie, Owner = Besitzer.
- New npm dependencies pinned exactly: `i18next@26.4.2`, `react-i18next@17.0.15`.
- Tools (scratch venv `V=/tmp/claude-1000/-home-andreas-work-family-budget-dashboard/bddd66bf-d388-43ab-9697-f451f8c8ad58/scratchpad/venv/bin`):
  full suite `$V/pytest tests -q -p no:warnings`; from `backend/`: `$V/black --check app ../tools ../tests`,
  `$V/flake8 app ../tools --max-line-length=120 --extend-ignore=E203,W503`,
  `$V/mypy app/ ../tools/ --ignore-missing-imports`; frontend `npm run lint && npm run type-check`;
  browser tests `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npm test`.

## Review Focus

1. A logged-in German person whose request also carries `Accept-Language: en` (English browser) → German errors
   (the person's setting wins). Test in Task 1.
2. An import file written with the German name of a 🔒 category (`Unsortiert`) or with a renamed default category →
   imports like the English name; the import preview's dropdown shows the matching entry. Test in Task 4.
3. A parent tries to name a category `Ausgleich` or `unsorted` → "already exists", in either language. Test in Task 4.
4. A person with an old login token and no `language` stored → German, no error. Test in Task 1.
5. Error messages with numbers ("Try again in 1 minute" vs "2 minutes", "used by 1 transaction, 2 budgets") →
   correct singular/plural in both languages. Tests in Tasks 2 and 3.

---

## File Structure

Backend:
- Create `backend/app/i18n.py` — languages, default, request language (context variable), `Accept-Language`
  parsing, a person's language, 🔒 category names.
- Create `backend/app/messages.py` — the error catalog (`MESSAGES`), `text()`, `plural()`, `api_error()`.
- Modify `backend/app/main.py` — app-wide dependency `i18n.language_from_header`.
- Modify `backend/app/auth.py` — set the request language from the logged-in person.
- Modify `backend/app/schemas.py` — `User.language`, `LanguageUpdate`, `Category` display name.
- Modify `backend/app/api.py` — `PATCH /me/language`; errors via `api_error`.
- Modify every module raising `HTTPException`: `api.py`, `auth.py`, `common_api.py`, `categories_api.py`,
  `wishes_api.py`, `import_api.py`, `import_rules.py`, `privacy.py`, `month_check.py`.
- Modify `backend/app/seed.py` — German default names; `backend/app/reports.py`, `import_rules.py`,
  `import_api.py`, `categories_api.py` — display names, both names on import, reserved names.
- Tests: `tests/conftest.py`, `tests/test_language.py`, `tests/test_messages.py`, `tests/test_system_category_names.py`.

Frontend:
- Create `frontend/src/i18n.ts`, `frontend/src/locales/de.ts`, `frontend/src/locales/en.ts`,
  `frontend/src/i18next.d.ts`, `frontend/src/format.ts`, `frontend/scripts/check-texts.mjs`.
- Modify `frontend/package.json`, `frontend/src/main.tsx`, `frontend/src/api.ts`, `frontend/src/AuthContext.tsx`,
  `frontend/src/components/Logins.tsx`, then every component and page (Tasks 7–10).
- E2E: `e2e/playwright.config.ts`, `e2e/tests/german.spec.ts`.
- Docs: `README.md`, `README_DOCKER.md`, `.env.example`, `docker-compose.yml`.

---

### Task 1: Language setting and request language

**Files:**
- Create: `backend/app/i18n.py`
- Modify: `backend/app/main.py`, `backend/app/auth.py:63-84`, `backend/app/models.py` and `backend/app/schemas.py` (class `User`), `backend/app/api.py` (next to `PATCH /me/privacy`)
- Modify: `tests/conftest.py`
- Test: `tests/test_language.py`

**Interfaces:**
- Produces: `i18n.LANGUAGES: tuple[str, ...]`, `i18n.default_language() -> str`, `i18n.current() -> str`,
  `i18n.set_current(lang: Optional[str]) -> None`, `i18n.from_header(value: Optional[str]) -> Optional[str]`,
  `i18n.user_language(user: models.User) -> str`, `async i18n.language_from_header(request: Request) -> None`;
  `schemas.User.language: str`; `schemas.LanguageUpdate(language: Literal["de", "en"])`;
  endpoint `PATCH /api/v1/me/language` → `schemas.User`.

- [ ] **Step 1: Make the test run English by default**

At the top of `tests/conftest.py`, next to `DATABASE_URL`:

```python
# The existing tests check English texts and English default categories; German tests set "de" themselves
os.environ["DEFAULT_LANGUAGE"] = "en"
```

- [ ] **Step 2: Write the failing tests** — `tests/test_language.py`

```python
"""Each person's language (issue #50): stored in users.settings, German by default, used for error messages."""

from helpers import BASE_URL, admin_headers, login, register

from app import i18n


def me(client, headers):
    return client.get(f"{BASE_URL}/me", headers=headers).json()


def test_language_defaults_to_the_configured_default(client, monkeypatch):
    mum = register(client, "mum")
    assert me(client, mum)["language"] == "en"
    monkeypatch.setenv("DEFAULT_LANGUAGE", "de")
    assert me(client, mum)["language"] == "de"


def test_unsupported_default_falls_back_to_german(monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "fr")
    assert i18n.default_language() == "de"
    monkeypatch.delenv("DEFAULT_LANGUAGE")
    assert i18n.default_language() == "de"


def test_set_language(client):
    mum = register(client, "mum")
    response = client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    assert response.status_code == 200 and response.json()["language"] == "de"
    assert me(client, mum)["language"] == "de"
    assert me(client, login(client, "mum"))["language"] == "de"


def test_other_settings_are_kept(client):
    mum = register(client, "mum")
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    client.patch(f"{BASE_URL}/me/language", json={"language": "en"}, headers=mum)
    assert me(client, mum)["language"] == "en"


def test_unknown_language_is_rejected(client):
    mum = register(client, "mum")
    assert client.patch(f"{BASE_URL}/me/language", json={"language": "fr"}, headers=mum).status_code == 422


def test_children_choose_their_own_language(client):
    kid = register(client, "kid", role="CHILD")
    assert client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=kid).status_code == 200


def test_accept_language_parsing():
    assert i18n.from_header("de-CH,de;q=0.9,en;q=0.8") == "de"
    assert i18n.from_header("en-US,en;q=0.9") == "en"
    assert i18n.from_header("fr-CH, en;q=0.5, de;q=0.7") == "de"
    assert i18n.from_header("fr") is None
    assert i18n.from_header("") is None
    assert i18n.from_header(None) is None
    assert i18n.from_header("de;q=garbage, en") == "en"
```

The tests for errors in the right language (person's setting beats `Accept-Language`, header before login) are in
Task 2, where the first message is translated.

- [ ] **Step 3: Run them to see them fail**

Run: `$V/pytest tests/test_language.py -q -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'i18n'`.

- [ ] **Step 4: Create `backend/app/i18n.py`**

```python
"""The language of a request (issue #50): German or English.

A person's own setting (users.settings["language"]) once their login is checked; before that, the browser's
Accept-Language; otherwise DEFAULT_LANGUAGE (environment, German if unset). The language lives in a context
variable for the request, so error messages and category names can be translated without passing it around.
"""

import os
from contextvars import ContextVar
from typing import Optional

from fastapi import Request

from typing import TYPE_CHECKING

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


async def language_from_header(request: Request) -> None:
    """App-wide dependency: every request starts in the browser's language (or the default)."""
    set_current(from_header(request.headers.get("accept-language")))
```

Note: `language_from_header` and `get_current_user_from_token` are **async** dependencies, so the context variable
they set is seen by the sync endpoints and dependencies FastAPI runs afterwards (threadpool calls copy the context).

- [ ] **Step 5: Wire it in**

`backend/app/main.py`: `from fastapi import Depends, FastAPI` and add `dependencies=[Depends(i18n.language_from_header)]`
to the `FastAPI(...)` call; import `i18n` with the other app modules.

`backend/app/auth.py`, at the end of `get_current_user_from_token`, before `return user`:

```python
    # From here on, the request speaks the person's language
    i18n.set_current(i18n.user_language(user))
```

`backend/app/models.py`, class `User`, a read-only property (imported lazily: `i18n` imports `models` for types):

```python
    @property
    def language(self) -> str:
        """Stored in settings; the default language if none was chosen."""
        from . import i18n

        return i18n.user_language(self)
```

`backend/app/schemas.py`, class `User` (the response model of `/me` and `/users`, `from_attributes`) gets the field
`language: str = "de"`, read from that property.

and a new schema:

```python
class LanguageUpdate(BaseModel):
    language: Literal["de", "en"]
```

`backend/app/api.py`, next to `PATCH /me/privacy`:

```python
@router.patch("/me/language", response_model=schemas.User)
def set_language(
    change: schemas.LanguageUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_from_token),
):
    # A new dict, so SQLAlchemy sees the JSON column change
    current_user.settings = {**(current_user.settings or {}), "language": change.language}
    db.commit()
    db.refresh(current_user)
    i18n.set_current(change.language)
    return current_user
```

- [ ] **Step 6: Run the tests**

Run: `$V/pytest tests/test_language.py -q -p no:warnings`
Expected: 7 passed.

- [ ] **Step 7: Full suite, lint, commit**

Run the full suite, black, flake8, mypy. Expected: all green.

```bash
git add backend/app/i18n.py backend/app/main.py backend/app/auth.py backend/app/models.py backend/app/schemas.py backend/app/api.py tests/conftest.py tests/test_language.py
git commit -m "feat: each person's language, and the request's language (#50)"
```

---

### Task 2: Error catalog, first messages translated

**Files:**
- Create: `backend/app/messages.py`
- Modify: `backend/app/api.py` (login errors: lines ~80-105), `backend/app/auth.py` (`credentials_exception`)
- Test: `tests/test_messages.py`

**Interfaces:**
- Consumes: `i18n.current()`, `i18n.LANGUAGES`.
- Produces: `messages.MESSAGES: dict[str, dict[str, str]]` (language → key → text),
  `messages.text(key: str, **params) -> str`, `messages.plural(key: str, count: int, **params) -> str`
  (picks `key + "_one"` or `key + "_other"`, passes `count`),
  `messages.api_error(status_code: int, key: str, headers: Optional[dict] = None, **params) -> HTTPException`.

- [ ] **Step 1: Write the failing tests** — `tests/test_messages.py`

```python
"""Error messages in the caller's language (issue #50)."""

import re
import string

from helpers import BASE_URL, register

from app import messages

WRONG = {"username": "nobody", "pin": "9999"}


def test_wrong_pin_before_login_follows_the_browser(client):
    german = client.post(f"{BASE_URL}/login", json=WRONG, headers={"Accept-Language": "de-CH,de;q=0.9"})
    english = client.post(f"{BASE_URL}/login", json=WRONG, headers={"Accept-Language": "en-US"})
    assert german.json()["detail"] == messages.MESSAGES["de"]["wrong_login"]
    assert english.json()["detail"] == messages.MESSAGES["en"]["wrong_login"]


def test_without_a_header_the_default_applies(client, monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "de")
    assert client.post(f"{BASE_URL}/login", json=WRONG).json()["detail"] == messages.MESSAGES["de"]["wrong_login"]


def test_the_persons_setting_beats_the_browser(client):
    mum = register(client, "mum")
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    response = client.delete(f"{BASE_URL}/categories/nope", headers={**mum, "Accept-Language": "en"})
    assert response.json()["detail"] == messages.MESSAGES["de"]["category_not_found"]


def test_too_many_wrong_pins_counts_minutes():
    assert messages.plural("login_locked", 1) != messages.plural("login_locked", 2)
    assert "2" in messages.plural("login_locked", 2)


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_message_exists_in_both_languages_with_the_same_placeholders():
    de, en = messages.MESSAGES["de"], messages.MESSAGES["en"]
    assert de.keys() == en.keys()
    for key in de:
        assert placeholders(de[key]) == placeholders(en[key]), key


def test_german_texts_use_swiss_spelling():
    assert not [k for k, t in messages.MESSAGES["de"].items() if "ß" in t]


def test_plural_keys_come_in_pairs():
    keys = messages.MESSAGES["en"].keys()
    for key in keys:
        if key.endswith("_one"):
            assert re.sub("_one$", "_other", key) in keys, key
```

(`test_the_persons_setting_beats_the_browser` needs `category_not_found`: convert `categories_api.py`'s
`"Category not found"` in this task, the rest of that file in Task 3.)

- [ ] **Step 2: Run them to see them fail**

Run: `$V/pytest tests/test_messages.py -q -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'messages'`.

- [ ] **Step 3: Create `backend/app/messages.py`**

```python
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
        "not_logged_in": "Anmeldung ungültig, bitte neu anmelden",
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
```

- [ ] **Step 4: Use it** — replace the English literals, keeping status codes and headers:
  - `auth.py` `credentials_exception` → `messages.api_error(401, "not_logged_in", headers={"WWW-Authenticate": "Bearer"})`.
    It is built before the token is checked, so it is in the browser's language — correct for an expired login.
  - `api.py` login lock → `HTTPException(status_code=..., detail=messages.plural("login_locked", minutes))` (keep
    its headers if any); wrong PIN → `messages.api_error(..., "wrong_login")`.
  - `categories_api.py:60` → `messages.api_error(404, "category_not_found")`.

The existing tests that assert these English texts keep passing (the test default is `en`).

- [ ] **Step 5: Run the tests**

Run: `$V/pytest tests/test_messages.py tests/test_language.py -q -p no:warnings`
Expected: all pass.

- [ ] **Step 6: Full suite, lint, commit**

```bash
git add backend/app/messages.py backend/app/api.py backend/app/auth.py backend/app/categories_api.py tests/test_messages.py
git commit -m "feat: error messages in the caller's language (#50)"
```

---

### Task 3: All remaining error messages

**Files:**
- Modify: `backend/app/api.py`, `common_api.py`, `categories_api.py`, `wishes_api.py`, `import_api.py`,
  `import_rules.py`, `privacy.py`, `month_check.py`, `backend/app/messages.py`
- Test: `tests/test_messages.py` (add the scan test)

**Interfaces:**
- Consumes: `messages.api_error`, `messages.plural`, `messages.text`.
- Produces: catalog keys for every error; no `HTTPException(detail="literal")` left in `backend/app`.

- [ ] **Step 1: Write the failing scan test** (append to `tests/test_messages.py`)

```python
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "backend" / "app"


def literal_details():
    """HTTPException(..., detail=<text>) written in the code instead of api_error()."""
    found = []
    for path in sorted(APP.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "HTTPException":
                for kw in node.keywords:
                    if kw.arg == "detail" and isinstance(kw.value, (ast.Constant, ast.JoinedStr)):
                        found.append(f"{path.name}:{node.lineno}")
    return found


def used_keys():
    keys = set()
    for path in sorted(APP.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("api_error", "text"):
                args = node.args[1:] if getattr(node.func, "attr", getattr(node.func, "id", "")) == "api_error" else node.args
                if args and isinstance(args[0], ast.Constant):
                    keys.add(args[0].value)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "plural":
                if node.args and isinstance(node.args[0], ast.Constant):
                    keys |= {node.args[0].value + "_one", node.args[0].value + "_other"}
    return keys


def test_no_error_text_outside_the_catalog():
    assert literal_details() == []


def test_every_used_key_is_in_the_catalog():
    assert used_keys() - messages.MESSAGES["en"].keys() == set()
```

- [ ] **Step 2: Run it to see it fail**

Run: `$V/pytest tests/test_messages.py::test_no_error_text_outside_the_catalog -q -p no:warnings`
Expected: FAIL listing about 110 `file.py:line` entries.

- [ ] **Step 3: Convert file by file**

For each file in the order `api.py`, `categories_api.py`, `common_api.py`, `wishes_api.py`, `import_api.py`,
`import_rules.py`, `privacy.py`, `month_check.py`:

1. List its literals: `$V/pytest tests/test_messages.py::test_no_error_text_outside_the_catalog -q -p no:warnings 2>&1 | grep <file>`.
2. For each one: pick a snake_case key named after the situation (`account_not_found`, `only_parents_categories`,
   `category_name_taken`, …); add the English text **unchanged** to `MESSAGES["en"]` and a German translation to
   `MESSAGES["de"]` (glossary and du-form from Global Constraints); replace the raise with
   `messages.api_error(<same status>, "<key>", **params)`. Keep every `headers=`.
3. f-strings become placeholders: `f"Unknown account '{name}'"` → `"Unknown account '{name}'"` with
   `name=name`. Text with a number gets `_one` / `_other` keys and `plural()`.
4. Shared constants (e.g. `LOCKED` in `categories_api.py`) become one key.
5. `categories_api.describe(counts)` ("used by 2 transactions, 1 budget") becomes plural keys per kind
   (`used_by_transactions_one/_other`, `used_by_budgets_…`, `used_by_planned_costs_…`, `used_by_import_rules_…`)
   joined by `", "` after `text("used_by")` ("used by" / "verwendet von"), and the error
   `"{used}; its type can't change"` / `"{used}; der Typ kann nicht mehr geändert werden"` → key `category_type_in_use` with
   `used=...`.
6. Strings that are **not** errors shown to people (log messages, CSV headers, JSON Schema, `toml` blocks,
   import row errors written into the preview) — import row errors **are** shown in the preview: translate them
   with `messages.text(...)` the same way. Log messages stay English.
7. Run the full suite after each file. Existing tests asserting English texts must pass unchanged — if one fails,
   the English text in the catalog differs from the old literal: fix the catalog, not the test.

Add, while converting `categories_api.py`, a German check to `tests/test_messages.py`:

```python
def test_category_in_use_counts_in_german(client, monkeypatch):
    from helpers import add_transaction, create_account, register
    mum = register(client, "mum")
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    category = client.post(f"{BASE_URL}/categories", json={"name": "Velo", "type": "EXPENSE"}, headers=mum).json()
    account = create_account(client, mum)
    add_transaction(client, mum, account, category["id"], 10)
    response = client.put(f"{BASE_URL}/categories/{category['id']}", json={"type": "INCOME"}, headers=mum)
    assert response.json()["detail"] == "verwendet von 1 Buchung; der Typ kann nicht mehr geändert werden"
```

(Check `helpers.add_transaction`'s signature before using it; it takes the category as the 4th argument.)

- [ ] **Step 4: Run the scan tests**

Run: `$V/pytest tests/test_messages.py -q -p no:warnings`
Expected: all pass, `literal_details() == []`.

- [ ] **Step 5: Full suite, lint, commit**

```bash
git add backend/app tests/test_messages.py
git commit -m "feat: every error message in German and English (#50)"
```

---

### Task 4: 🔒 categories in the caller's language

**Files:**
- Modify: `backend/app/i18n.py`, `backend/app/schemas.py` (class `Category`), `backend/app/reports.py:105`,
  `backend/app/import_rules.py` (`with_category`, `rule_out`), `backend/app/import_api.py` (`Lookups.categories`
  line ~132, the preview's `category`, the confirm step line ~348), `backend/app/categories_api.py` (`name_taken`)
- Test: `tests/test_system_category_names.py`

**Interfaces:**
- Consumes: `i18n.current()`.
- Produces: `i18n.SYSTEM_NAMES: dict[str, dict[str, str]]` (system_key → language → name),
  `i18n.category_name(category) -> str` (display name in the current language),
  `i18n.all_names(category) -> set[str]` (stored name plus both system names).

- [ ] **Step 1: Write the failing tests** — `tests/test_system_category_names.py`

```python
"""The 🔒 categories in each person's language; the stored (English) name stays the reference (issue #50)."""

from helpers import BASE_URL, create_account, register


def german(client, name="mum"):
    headers = register(client, name)
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=headers)
    return headers


def names(client, headers):
    return {c["system_key"]: c["name"] for c in client.get(f"{BASE_URL}/categories", headers=headers).json()}


def test_system_categories_in_the_persons_language(client):
    mum = german(client)
    dad = register(client, "dad")
    assert names(client, mum)["UNSORTED"] == "Unsortiert"
    assert names(client, mum)["SETTLE_UP"] == "Ausgleich"
    assert names(client, dad)["UNSORTED"] == "Unsorted"


def test_ordinary_categories_keep_their_name(client):
    mum = german(client)
    assert "Groceries" in [c["name"] for c in client.get(f"{BASE_URL}/categories", headers=mum).json()]


def import_csv(client, headers, category):
    create_account(client, headers, "Bank")
    csv = f"date,account,category,amount\n2026-10-01,Bank,{category},12.5\n"
    return client.post(f"{BASE_URL}/import/preview", files={"file": ("a.csv", csv, "text/csv")}, headers=headers)


def test_import_accepts_both_names(client):
    mum = german(client)
    for name in ("Unsortiert", "unsorted"):
        rows = import_csv(client, mum, name).json()["rows"]
        assert rows[0]["errors"] == [], rows[0]
        assert rows[0]["category"] == "Unsortiert"


def test_json_schema_keeps_the_english_names(client):
    mum = german(client)
    schema = client.get(f"{BASE_URL}/import/schema", headers=mum).json()
    enum = schema["items"]["properties"]["category"]["enum"]
    assert "Unsorted" in enum and "Unsortiert" not in enum


def test_both_names_are_reserved(client):
    mum = german(client)
    for name in ("Ausgleich", "unsorted", "Umbuchung"):
        response = client.post(f"{BASE_URL}/categories", json={"name": name, "type": "EXPENSE"}, headers=mum)
        assert response.status_code == 400, name


def test_report_shows_the_german_name(client):
    from helpers import add_transaction
    mum = german(client)
    account = create_account(client, mum)
    unsorted = next(c["id"] for c in client.get(f"{BASE_URL}/categories", headers=mum).json() if c["system_key"] == "UNSORTED")
    add_transaction(client, mum, account, unsorted, 10)
    report = client.get(f"{BASE_URL}/reports/summary", headers=mum).json()
    assert "Unsortiert" in str(report)
```

Before running, check the real paths and payloads in `import_api.py` (`/import/preview`, `/import/schema`, the
preview's row fields) and `reports.py` (endpoint and query parameters) and adjust the test calls to them — keep the
assertions. Ledger any path change as a ruling.

- [ ] **Step 2: Run them to see them fail**

Run: `$V/pytest tests/test_system_category_names.py -q -p no:warnings`
Expected: FAIL — `"Unsorted" != "Unsortiert"` and similar.

- [ ] **Step 3: Implement** — in `backend/app/i18n.py`:

```python
# The 🔒 categories by system_key; the English name is the one stored in the database
SYSTEM_NAMES = {
    "UNSORTED": {"en": "Unsorted", "de": "Unsortiert"},
    "UNKNOWN_EXPENSE": {"en": "Unknown expense", "de": "Unbekannte Ausgabe"},
    "OTHER_INCOME": {"en": "Other Income", "de": "Übrige Einnahmen"},
    "SETTLE_UP": {"en": "Settle up", "de": "Ausgleich"},
    "TRANSFER": {"en": "Transfer", "de": "Umbuchung"},
}


def category_name(category) -> str:
    """The name to show: a 🔒 category's in the request's language, any other its own."""
    names = SYSTEM_NAMES.get(category.system_key or "")
    return names[current()] if names else category.name


def all_names(category) -> set[str]:
    """Every name an import file may use for the category."""
    return {category.name, *SYSTEM_NAMES.get(category.system_key or "", {}).values()}
```

Then:
- `schemas.Category`: a `model_validator(mode="after")` that sets `self.name = i18n.SYSTEM_NAMES[self.system_key][i18n.current()]`
  when `self.system_key in i18n.SYSTEM_NAMES`.
- `reports.py:105`: `category.name` → `i18n.category_name(category)`.
- `import_rules.with_category`: `"category": i18n.category_name(category)`; `rule_out`: `"category": i18n.category_name(rule.category)`
  (the `toml` block keeps `category.name`).
- `import_api.Lookups.__init__`: `self.categories = {key(n): c for c in db.query(models.Category) for n in i18n.all_names(c)}`.
- `import_api` preview: after a row's category is found, its `category` field is `i18n.category_name(category)`
  (`file_category` keeps the file's text), so the preview's dropdown (values from `/categories`) matches.
- `import_api` confirm (line ~348): look the remembered category up with `lookups.categories[key(row["category"])]`
  instead of `models.Category.name == row["category"]`.
- `categories_api.name_taken`: compare against `i18n.all_names(c)` of every category (casefolded), not only `c.name`.
- JSON Schema (`enum`, `x-category-types`, `x-rules`) and `export_api.py`: unchanged (stored names).

- [ ] **Step 4: Run the tests**

Run: `$V/pytest tests/test_system_category_names.py -q -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Full suite, lint, commit**

```bash
git add backend/app tests/test_system_category_names.py
git commit -m "feat: system categories in the caller's language (#50)"
```

---

### Task 5: German default categories and the default-language setting

**Files:**
- Modify: `backend/app/seed.py`, `README.md`, `README_DOCKER.md`, `.env.example`, `docker-compose.yml`
- Test: `tests/test_system_category_names.py` (append)

**Interfaces:**
- Consumes: `i18n.default_language()`.
- Produces: `seed.DEFAULT_CATEGORIES` entries with an optional `"de"` name.

- [ ] **Step 1: Write the failing test** (append)

```python
from app import database, models
from app.seed import seed_categories


def fresh_install():
    models.Base.metadata.drop_all(bind=database.engine)
    models.Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        seed_categories(db)
        return {c.name for c in db.query(models.Category)}


def test_a_new_install_gets_german_categories(monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "de")
    created = fresh_install()
    assert {"Lebensmittel", "Miete", "Auswärts essen", "Rückerstattungen"} <= created
    assert "Groceries" not in created
    # 🔒 categories keep their English name in the database
    assert {"Unsorted", "Settle up", "Transfer"} <= created


def test_an_english_install_keeps_english_categories():
    assert {"Groceries", "Rent"} <= fresh_install()
```

- [ ] **Step 2: Run to see it fail**

Run: `$V/pytest tests/test_system_category_names.py -k install -q -p no:warnings`
Expected: FAIL — `Lebensmittel` missing.

- [ ] **Step 3: Implement** — in `seed.py` give each ordinary default a `"de"` name (spec section 4 table):
Salary/Lohn, Freelance/Nebenerwerb, Investment/Kapitalertrag, Gift/Geschenk, Groceries/Lebensmittel, Rent/Miete,
Utilities/Nebenkosten, Transportation/Mobilität, Entertainment/Freizeit, Healthcare/Gesundheit, Education/Bildung,
Clothing/Kleidung, Dining Out/Auswärts essen, Other Expense/Übrige Ausgaben, Reimbursements/Rückerstattungen.
In `seed_categories`, when creating all defaults on a new database:

```python
name = cat_data.get("de", cat_data["name"]) if i18n.default_language() == "de" else cat_data["name"]
```

and pass only the model's columns (drop the `"de"` key) to `models.Category(...)`.

Document `DEFAULT_LANGUAGE` (`de` default, or `en`: language of people who haven't chosen one, of the login screen
when the browser sends nothing usable, and of a new install's default categories) in `README.md` (next to
`INITIAL_ADMIN_PIN`), `README_DOCKER.md`, `.env.example` (`DEFAULT_LANGUAGE=`) and `docker-compose.yml`
(`- DEFAULT_LANGUAGE=${DEFAULT_LANGUAGE:-de}`).

- [ ] **Step 4: Run, full suite, lint, commit**

```bash
git add backend/app/seed.py tests/test_system_category_names.py README.md README_DOCKER.md .env.example docker-compose.yml
git commit -m "feat: German default categories on a new install (#50)"
```

---

### Task 6: Frontend i18n setup, language switch, dates, text check

**Files:**
- Modify: `frontend/package.json` (+ lock), `frontend/src/main.tsx`, `frontend/src/api.ts`,
  `frontend/src/AuthContext.tsx`, `frontend/src/components/Logins.tsx`, `e2e/playwright.config.ts`
- Create: `frontend/src/i18n.ts`, `frontend/src/locales/de.ts`, `frontend/src/locales/en.ts`,
  `frontend/src/i18next.d.ts`, `frontend/src/format.ts`, `frontend/scripts/check-texts.mjs`

**Interfaces:**
- Produces: `Language = 'de' | 'en'`; `browserLanguage(): Language`; `applyLanguage(lang: Language): void`
  (changes i18next and `<html lang>`); default export `i18n` (the i18next instance) from `src/i18n.ts`;
  `formatDate(value: string | Date): string`, `formatMonth(value: string | Date): string` from `src/format.ts`;
  `de` (default export of `src/locales/de.ts`) and `type Messages = typeof de`; `npm run check-texts`.

- [ ] **Step 1: Write the failing text check first** — `frontend/scripts/check-texts.mjs`

A node script using the `typescript` package (already a dev dependency) to parse every `src/**/*.tsx` file listed
in `CHECKED` and report visible English text outside the locale files:

```js
// Visible text must come from src/locales (issue #50): reports text written directly in the components.
// Checks JSX text, the attributes people see or hear, and string arguments of confirm/alert/setError/errorMessage.
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
// Files already translated; Tasks 7-10 add theirs, and the last one replaces this list with every .tsx file
const CHECKED = ['components/Logins.tsx'];
const ATTRIBUTES = new Set(['placeholder', 'aria-label', 'title', 'alt', 'label']);
const CALLS = new Set(['confirm', 'alert', 'setError', 'errorMessage', 'setMessage']);
const PROPERTIES = new Set(['label', 'text', 'title', 'placeholder']);
const WORD = /[A-Za-zÄÖÜäöü]{2,}/;

const problems = [];
for (const file of CHECKED) {
    const full = path.join(SRC, file);
    const source = ts.createSourceFile(full, fs.readFileSync(full, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const report = (node, text) => {
        const { line } = source.getLineAndCharacterOfPosition(node.getStart());
        problems.push(`${file}:${line + 1}: ${text.trim().slice(0, 60)}`);
    };
    const literal = (node) => ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ? node.text
        : ts.isTemplateExpression(node) ? [node.head.text, ...node.templateSpans.map(s => s.literal.text)].join(' ') : null;
    const visit = (node) => {
        if (ts.isJsxText(node) && WORD.test(node.text)) report(node, node.text);
        if (ts.isJsxAttribute(node) && ATTRIBUTES.has(node.name.getText()) && node.initializer) {
            const value = ts.isJsxExpression(node.initializer) ? node.initializer.expression : node.initializer;
            const text = value && literal(value);
            if (text && WORD.test(text)) report(node, text);
        }
        if (ts.isJsxExpression(node) && node.expression) {
            const text = literal(node.expression);
            if (text && WORD.test(text)) report(node, text);
        }
        if (ts.isCallExpression(node) && CALLS.has(node.expression.getText().split('.').pop())) {
            for (const arg of node.arguments) {
                const text = literal(arg);
                if (text && WORD.test(text)) report(arg, text);
            }
        }
        if (ts.isPropertyAssignment(node) && PROPERTIES.has(node.name.getText())) {
            const text = literal(node.initializer);
            if (text && WORD.test(text)) report(node, text);
        }
        ts.forEachChild(node, visit);
    };
    visit(source);
}
if (problems.length) {
    console.error(`Text outside src/locales (use t()):\n${problems.join('\n')}`);
    process.exit(1);
}
```

In `package.json` scripts: `"check-texts": "node scripts/check-texts.mjs"` and append `&& npm run check-texts` to
`"lint"` (CI runs `npm run lint`). If `import.meta.dirname` is not available in the installed Node, use
`path.dirname(new URL(import.meta.url).pathname)`.

- [ ] **Step 2: Run it to see it fail**

Run: `cd frontend && npm run check-texts`
Expected: FAIL listing `components/Logins.tsx` lines ("Log out on every device…", "Log out everywhere", …).

- [ ] **Step 3: Install and set up i18next**

```bash
cd frontend && npm install --save-exact i18next@26.4.2 react-i18next@17.0.15
```

`src/locales/de.ts`:

```ts
// German texts (Swiss spelling: ss, never ß; informal du). en.ts must have the same keys (tsc checks it).
const de = {
    common: {
        save: 'Speichern',
        cancel: 'Abbrechen',
        delete: 'Löschen',
        edit: 'Bearbeiten',
    },
    logins: {
        title: 'Anmeldungen',
        intro: 'Eine Anmeldung gilt auf jedem Gerät etwa zwei Tage. Geht ein Handy oder Computer verloren, beende alle deine Anmeldungen auf einmal; danach meldest du dich mit deiner PIN wieder an. Eine neue PIN tut dasselbe für diese Person.',
        logoutEverywhere: 'Überall abmelden',
        confirmLogoutEverywhere: 'Auf allen Geräten abmelden, auch auf diesem?',
        logoutFailed: 'Überall abmelden fehlgeschlagen',
        language: 'Sprache',
        languageFailed: 'Sprache konnte nicht gespeichert werden',
        german: 'Deutsch',
        english: 'English',
    },
};
export default de;
export type Messages = typeof de;
```

`src/locales/en.ts` (texts copied unchanged from the current `Logins.tsx`):

```ts
import type { Messages } from './de';

const en: Messages = {
    common: {
        save: 'Save',
        cancel: 'Cancel',
        delete: 'Delete',
        edit: 'Edit',
    },
    logins: {
        title: 'Logins',
        intro: 'A login lasts about two days on each device. If a phone or computer gets lost, end all your logins at once; you then log in again with your PIN. Changing a PIN does the same for that person.',
        logoutEverywhere: 'Log out everywhere',
        confirmLogoutEverywhere: 'Log out on every device, this one included?',
        logoutFailed: 'Failed to log out everywhere',
        language: 'Language',
        languageFailed: 'Failed to save the language',
        german: 'Deutsch',
        english: 'English',
    },
};
export default en;
```

`src/i18next.d.ts`:

```ts
import 'i18next';
import type de from './locales/de';

declare module 'i18next' {
    interface CustomTypeOptions {
        resources: { translation: typeof de };
    }
}
```

`src/i18n.ts`:

```ts
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import de from './locales/de';
import en from './locales/en';

export type Language = 'de' | 'en';

// Before login (and after logout) the browser decides; after login the person's own setting
export const browserLanguage = (): Language => (navigator.language.toLowerCase().startsWith('de') ? 'de' : 'en');

i18n.use(initReactI18next).init({
    resources: { de: { translation: de }, en: { translation: en } },
    lng: browserLanguage(),
    fallbackLng: 'de',
    interpolation: { escapeValue: false },
});
document.documentElement.lang = i18n.language;

export function applyLanguage(lang: Language) {
    if (i18n.language !== lang) i18n.changeLanguage(lang);
    document.documentElement.lang = lang;
}

export default i18n;
```

`src/main.tsx`: `import './i18n';` before `import App`.

`src/api.ts` request interceptor: `config.headers['Accept-Language'] = i18n.language;` (import `i18n` from `./i18n`).

`src/AuthContext.tsx`: `User` gets `language: Language`; wherever `setUser(response.data)` runs after `/me`, call
`applyLanguage(response.data.language)`; in `logout`, `applyLanguage(browserLanguage())`.

`src/format.ts`:

```ts
import i18n from './i18n';

// Dates in the current language: 16.10.2026 / 16 Oct 2026, Oktober 2026 / October 2026
const locale = () => (i18n.language === 'de' ? 'de-CH' : 'en-GB');

// "2026-10" means the month; the 15th at noon keeps it in that month in every time zone
const toDate = (value: string | Date) =>
    value instanceof Date ? value : new Date(/^\d{4}-\d{2}$/.test(value) ? `${value}-15T12:00:00` : value);

export const formatDate = (value: string | Date) =>
    toDate(value).toLocaleDateString(locale(), i18n.language === 'de'
        ? { day: '2-digit', month: '2-digit', year: 'numeric' }
        : { day: 'numeric', month: 'short', year: 'numeric' });

export const formatMonth = (value: string | Date) =>
    toDate(value).toLocaleDateString(locale(), { month: 'long', year: 'numeric' });
```

- [ ] **Step 4: Translate `Logins.tsx` and add the switch**

Use `const { t } = useTranslation();` and the `logins.*` keys for every text. Add, next to the button:

```tsx
<label className="flex items-center gap-2 text-sm">
    {t('logins.language')}
    <select aria-label={t('logins.language')} value={user?.language ?? i18n.language}
        onChange={e => changeLanguage(e.target.value as Language)}
        className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white">
        <option value="de">{t('logins.german')}</option>
        <option value="en">{t('logins.english')}</option>
    </select>
</label>
```

with

```ts
const changeLanguage = async (language: Language) => {
    try {
        await api.patch('/api/v1/me/language', { language });
        // Everything already loaded (e.g. the 🔒 category names) comes again in the new language
        window.location.reload();
    } catch (err) {
        setError(errorMessage(err, t('logins.languageFailed')));
    }
};
```

(Language names are shown in their own language in both files. `Logins.tsx` already has `error` state; get `user`
from `useAuth()` as well.)

- [ ] **Step 5: E2E backend in English**

`e2e/playwright.config.ts`: add `DEFAULT_LANGUAGE: 'en'` to the backend `env`, and `locale: 'en-US'` to `use`.

- [ ] **Step 6: Verify**

Run: `cd frontend && npm run lint && npm run type-check && npm run build`
Expected: all pass (check-texts passes for `Logins.tsx`).
Break it on purpose: delete `logins.language` from `en.ts` → `npm run type-check` fails; restore. Write
`t('logins.nope')` → type-check fails; restore.
Run the browser tests: `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npm test` → 11 passed (logout-everywhere
still finds "Log out everywhere").

- [ ] **Step 7: Commit**

```bash
git add frontend e2e/playwright.config.ts
git commit -m "feat: frontend translations setup and language switch (#50)"
```

---

### Tasks 7–10: Translate the components

Each of these four tasks follows the same steps; only the files differ.

**Files per task:**
- **Task 7:** `App.tsx`, `pages/Login.tsx`, `pages/dashboard/Dashboard.tsx`, `components/PinInput.tsx`,
  `components/ScopeSelector.tsx`, `components/OwnerSelect.tsx`, `components/AccountCards.tsx`, and visible texts in
  `finance.ts`, `accounts.ts`, `family.ts`, `ownership.ts`, `useFamily.ts` (labels such as account types).
- **Task 8:** `components/Transactions.tsx`, `BudgetManager.tsx`, `Analytics.tsx`, `MonthCheck.tsx`,
  `CategoryManager.tsx`.
- **Task 9:** `components/CommonBudget.tsx`, `SplitManager.tsx`, `YearlyBills.tsx`, `MonthlyCosts.tsx`,
  `Investments.tsx`, `Wishes.tsx`.
- **Task 10:** `components/FamilyManager.tsx`, `RemoveMember.tsx`, `ShareSettings.tsx`, `DataManager.tsx`,
  `ImportTransactions.tsx`, `ImportRules.tsx`; then `CHECKED` in `check-texts.mjs` becomes every `.tsx` under `src`
  (`fs.readdirSync(SRC, { recursive: true }).filter(f => f.endsWith('.tsx'))`).

**Interfaces:**
- Consumes: `useTranslation()` / `t` from `react-i18next`; `i18n.t` for code outside components; `formatDate`,
  `formatMonth` from `src/format.ts`; `Messages` type.
- Produces: one top-level key group per component in `de.ts` / `en.ts` (`dashboard`, `login`, `transactions`, …).

- [ ] **Step 1: Make the check fail** — add the task's files to `CHECKED` in `frontend/scripts/check-texts.mjs`.
Run `cd frontend && npm run check-texts`. Expected: FAIL listing the texts of those files.

- [ ] **Step 2: Move every listed text into the locale files**, file by file:
  - English text into `en.ts` **unchanged** (the browser tests find elements by these texts), German into `de.ts`
    (glossary, Swiss spelling, du-form).
  - Interpolation: `` `Due ${x}` `` → `t('bills.due', { date: x })` with `'Due {{date}}'` / `'Fällig {{date}}'`.
  - Counts: `count_one` / `count_other` keys and `t('x.count', { count })`; remove hand-made plural code
    (e.g. `WORDS` in `CategoryManager.tsx` becomes `categories.usedBy.transactions_one` … ).
  - Texts in constants outside the component (e.g. `GROUPS` labels): keep the key in the constant
    (`labelKey: 'categories.groups.income' as const`) and call `t(group.labelKey)` when rendering.
  - Texts the check does not catch but people see — status messages (`setStatus({ text })`), toast texts,
    `<option>` labels built from maps, `Dismiss error` aria-labels — move them as well; read each file top to bottom,
    not only the check's list.
  - Every `toLocaleDateString(...)` → `formatDate(...)` or `formatMonth(...)`
    (`MonthCheck.tsx`'s month name → `formatMonth(month)`).
  - Sentences built from parts (`nameOf(...).replace('You', 'you')` in `CommonBudget.tsx`): give the whole sentence
    one key with placeholders (`'{{from}} paid {{to}} {{amount}}'`), and a separate `common.you` / `common.youLower`
    for the person themself, so German word order works.
- [ ] **Step 3: Verify**

Run: `cd frontend && npm run lint && npm run type-check && npm run build`
Expected: all pass.
Run the browser tests: `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npm test`
Expected: 11 passed (English texts unchanged). A failing test means an English text changed — restore the English
text, not the test.
Spot-check German: start the dev servers (backend with `DEFAULT_LANGUAGE=de`), log in, switch to Deutsch, open each
screen of the task; no English text, no raw key like `transactions.title`.

- [ ] **Step 4: Commit**

```bash
git add frontend
git commit -m "feat: login, menu and accounts in German and English (#50)"        # Task 7
git commit -m "feat: transactions, budgets, analytics, month check and categories in German and English (#50)"  # Task 8
git commit -m "feat: common budget, bills, costs, investments and wishes in German and English (#50)"  # Task 9
git commit -m "feat: family, sharing, data and import in German and English (#50)"  # Task 10
```
(one of these per task)

---

### Task 11: Browser test in German, final checks

**Files:**
- Create: `e2e/tests/german.spec.ts`

**Interfaces:**
- Consumes: `newParent`, `call`, `login` from `e2e/tests/helpers.ts`; the German texts of Tasks 6–10.

- [ ] **Step 1: Write the test**

```ts
import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Switching to German (#50): menu, dates, a 🔒 category and a backend error in German, then back to English
test('switch the app to German and back', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Bank', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const unsorted = categories.find((c: { system_key: string }) => c.system_key === 'UNSORTED').id;
    await call(request, parent, 'POST', '/transactions', {
        account_id: account.id, category_id: unsorted, amount: 12.5, date: '2026-10-16T12:00:00',
    });

    const errors = await login(page, parent);
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByLabel('Language').selectOption('de');
    await expect(page.getByRole('button', { name: 'Einstellungen' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');

    // A 🔒 category and a date in German, in the transaction list
    await page.getByRole('button', { name: 'Konten' }).click();
    await expect(page.getByText('Unsortiert').first()).toBeVisible();
    await expect(page.getByText('16.10.2026').first()).toBeVisible();

    // A backend error in German: a category name that exists already
    await page.getByRole('button', { name: 'Einstellungen' }).click();
    const section = page.locator('section', { has: page.getByRole('heading', { name: 'Kategorien' }) });
    await section.getByLabel('Name der neuen Kategorie').fill('Ausgleich');
    await section.getByRole('button', { name: 'Kategorie hinzufügen' }).click();
    await expect(section).toContainText('Eine Kategorie mit diesem Namen gibt es schon');

    await page.getByLabel('Sprache').selectOption('en');
    await expect(page.getByRole('button', { name: 'Settings' })).toBeVisible();
    expect(errors).toEqual([]);
});
```

Before running, align the German strings in this test with the ones actually written in `de.ts` and
`messages.py` (tab labels, the categories heading and labels, `category_name_taken`), and where the transactions
list shows a booking's category and date (open the screen once). Keep what the test checks.

- [ ] **Step 2: Run it**

Run: `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npm test`
Expected: 12 passed.
Break it on purpose: change `'Unsortiert'` in `backend/app/i18n.py` to `'Unsortierte'` → the test fails; restore.

- [ ] **Step 3: Final checks**

Full pytest suite, black, flake8, mypy; `cd frontend && npm run lint && npm run type-check && npm run build`; all
browser tests. Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add e2e/tests/german.spec.ts
git commit -m "test: the app in German in the browser (#50)"
```
