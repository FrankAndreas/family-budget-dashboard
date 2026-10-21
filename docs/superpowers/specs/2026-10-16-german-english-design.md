# German and English with a language switch

Date: 2026-10-16. Status: draft, for review. Issue: #50.

## Goal

The app is English only. Every person should use it in German or English:

- **Per person:** each login picks German or English in Settings; the choice follows them to every device.
- **Everything visible is translated:** the frontend's texts, the backend's error messages and the names of the 🔒
  system categories.
- **German by default:** new installs, new people and people who never chose a language get German.

Decided with the user:
- The language is stored per person (not per device, not per family).
- Only the 5 🔒 system categories are translated. All other categories are the family's own data with one name; a
  new install creates its default categories with German names.
- Approach A: `react-i18next` in the frontend; the backend translates its own error messages from a small catalog.

Out of scope: more languages (the structure allows them later), translating the family's own categories, and
translating machine data (export ZIP, CSV columns, JSON Schema field names, log messages), which stays English so
converters and analysis scripts keep working.

## 1. Language setting (backend)

- Stored in the existing JSON column `users.settings` as `{"language": "de" | "en"}`. **No migration.**
- `GET /me` returns `language`: the stored value, or `de` if none is stored (all current users).
- New `PATCH /me/language` with `{"language": "de" | "en"}` stores it for the logged-in person and returns the
  updated user. Any other value is rejected with 422. Children with a login can change their own language, like
  every other person.
- New people (registered or added by a parent) store nothing and therefore get `de`.

## 2. Which language a request gets (backend)

New module `app/i18n.py`:

- `LANGUAGES = ("de", "en")`. `DEFAULT_LANGUAGE` is read from the environment variable `DEFAULT_LANGUAGE` (`de` if
  unset or not a supported language). The NAS sets nothing and gets German; the browser tests' backend sets `en`.
- `request_language(request, user)`:
  1. a logged-in person: their language (stored value, else `DEFAULT_LANGUAGE`);
  2. no logged-in person (login, setup): the first supported language in the `Accept-Language` header
     (`de-CH,de;q=0.9,en;q=0.8` → `de`; `en-US` → `en`; `fr` → none);
  3. otherwise `DEFAULT_LANGUAGE`.
- A FastAPI dependency makes the language available to every endpoint; endpoints that already resolve the current
  user use that user's language.

## 3. Error messages (backend)

- New module `app/messages.py`: one dict per language, `key → text`, with `str.format` placeholders, e.g.
  `"category_not_found": "Category not found"` / `"Kategorie nicht gefunden"`.
- A helper `api_error(status, key, lang, **params)` returns the `HTTPException` with the translated `detail`. All
  117 `HTTPException(detail="…")` in `backend/app` change to it.
- Messages assembled from parts get real plurals in both languages, e.g. the category-in-use text: "used by 1
  transaction, 2 budgets" / "verwendet von 1 Buchung, 2 Budgets". Plural forms are separate keys (`…_one`,
  `…_other`); a small `plural(key, count, lang)` picks one.
- FastAPI's own validation errors (422 from Pydantic) stay as they are: the frontend shows its own translated
  fallback text for them (section 6).
- The frontend's `errorMessage()` stays unchanged: it shows `detail` as before.

## 4. 🔒 System categories

- The database keeps the current English name. It stays the stable reference for the export ZIP, the JSON Schema
  (`enum`, `x-category-types`, `x-rules`) and the converter's `converter.toml`.
- Everywhere the app **shows** a category, the 🔒 ones appear in the caller's language, looked up by `system_key`
  (`display_name(category, lang)`): category lists, transactions, reports, the import preview, import rules and the
  common budget.

| `system_key` | English (stored) | German |
|---|---|---|
| `UNSORTED` | Unsorted | Unsortiert |
| `UNKNOWN_EXPENSE` | Unknown expense | Unbekannte Ausgabe |
| `OTHER_INCOME` | Other Income | Übrige Einnahmen |
| `SETTLE_UP` | Settle up | Ausgleich |
| `TRANSFER` | Transfer | Umbuchung |

- **Imports** accept both names of a 🔒 category (`Unsorted` and `Unsortiert`), case-insensitively as today.
- **Names are reserved in both languages:** a new or renamed category can't be called `Unsortiert` or `Unsorted`
  ("A category with that name already exists").
- **New installs** create the other 15 default categories in `DEFAULT_LANGUAGE`, so German unless configured:

| English (today) | German |
|---|---|
| Salary | Lohn |
| Freelance | Nebenerwerb |
| Investment | Kapitalertrag |
| Gift | Geschenk |
| Groceries | Lebensmittel |
| Rent | Miete |
| Utilities | Nebenkosten |
| Transportation | Mobilität |
| Entertainment | Freizeit |
| Healthcare | Gesundheit |
| Education | Bildung |
| Clothing | Kleidung |
| Dining Out | Auswärts essen |
| Other Expense | Übrige Ausgaben |
| Reimbursements | Rückerstattungen |

  Existing databases (the NAS) keep their categories; a parent can rename them in Settings → Categories.

## 5. Frontend setup

- New dependencies `i18next` and `react-i18next` (exact versions, at least two weeks old).
- `src/i18n.ts` sets them up; texts live in `src/locales/de.ts` and `src/locales/en.ts`, bundled with the app.
- Keys are grouped by screen: `categories.add`, `transactions.title`, `common.save`, …
- **Type-checked texts:** `en.ts` is declared with the type of `de.ts`, so a missing or extra key fails `tsc`.
  react-i18next's type augmentation makes `t('no.such.key')` a type error. The existing CI type check guards both;
  no frontend test runner is added.
- Placeholders and plurals use i18next's format (`{{count}}`, `_one` / `_other`).

## 6. Frontend behaviour

- **Before login:** the browser's language decides: `navigator.language` starting with `de` → German, else English.
- **After login:** the person's `language` from `/me`. On logout the browser's language applies again.
- `<html lang>` follows the current language.
- The axios client sends the current language as `Accept-Language` with every call, so errors before login (e.g.
  "Wrong PIN") match the screen.
- **The switch:** Settings → Logins, next to "Log out everywhere": a dropdown *Deutsch* / *English*. A change calls
  `PATCH /me/language` and then reloads the page, so every list already loaded (🔒 category names from the backend)
  is fetched again in the new language.
- **Dates:** new `src/format.ts` with `formatDate(value)` and `formatMonth(value)` for the current language
  replaces every `toLocaleDateString` call (today a mix of `'en'`, `'de-CH'` and the browser default):
  German `16.10.2026` and `Oktober 2026`, English `16 Oct 2026` and `October 2026`.
- **Amounts:** `money()` stays `CHF 1'234.50` in both languages.
- **All visible text moves into the locale files:** the 22 components, the Dashboard and Login, including
  `confirm()` texts, `placeholder`, `aria-label` and `title` attributes, and fallback error texts such as
  `'Failed to load categories'`.

## 7. Tests

Backend (pytest, TDD):
- `PATCH /me/language` stores the language; invalid values give 422; `/me` returns it; a person without one gets `de`.
- Language choice: the person's setting beats `Accept-Language`; `Accept-Language` applies before login; the
  fallback is `de` (checked with the "Wrong PIN" message in both languages).
- Catalog: every key exists in both languages with the same placeholders; every key passed to `api_error` in
  `backend/app` exists in the catalog.
- 🔒 categories: shown in the caller's language; imports accept both names; the JSON Schema keeps the English names;
  both names are reserved.
- A new install gets the default categories in `DEFAULT_LANGUAGE` (German by default, English with `en`).
- The existing tests check English texts and English category names ("Groceries"). The test run sets
  `DEFAULT_LANGUAGE=en` (in `tests/conftest.py`), so they stay unchanged; the tests above set it to `de` where
  they check the German default.

Frontend: `tsc` and lint (section 5).

Browser tests (Playwright):
- The 11 existing tests stay English: their backend starts with `DEFAULT_LANGUAGE=en` (English categories, English
  for people without a setting), and the browser runs with an English locale.
- One new test: log in, switch to Deutsch, check German menu labels, a German date, a 🔒 category as "Unsortiert"
  and a German error message, then switch back to English.

## 8. Delivery

One branch (`feat/german-english`), commits by area (backend; frontend setup, switch and `format.ts`; components in
a few batches), one PR at the end so `main` never has a half-translated app. Deploying to the NAS is a separate
step when the user asks.
