# Manage categories in Settings

Date: 2026-10-16. Status: draft, for review. Issue #22.

## Goal

Parents can add, rename and delete categories, and set their type and icon, so categories fit the family (e.g. "Car
leasing", "Gift cards & bonuses", also for the converters' rules). Today categories are only seeded at start-up, and
`POST /categories` has no screen.

Decided with the user: system categories are locked; seeded categories other than those can be renamed; delete only
when nothing uses the category; no merging (later, if needed).

## 1. System categories

Five categories carry meaning in the code and get a fixed key in a new column `categories.system_key` (unique,
nullable):

| Key | Name today | Used by |
|---|---|---|
| `TRANSFER` | Transfer | import (transfers), import rules, converters |
| `SETTLE_UP` | Settle up | settling up in the Common tab |
| `UNSORTED` | Unsorted | import rules (fallback rows), converter fallback |
| `UNKNOWN_EXPENSE` | Unknown expense | month check |
| `OTHER_INCOME` | Other Income | month check, import rules (fallback rows), converter fallback |

- The code finds them by key (`seed.system_category(db, key)`), not by name: `common_api` (settle up), `api`
  (settle-up checks), `import_api` / `import_rules` (Settle up, fallbacks), `month_check`.
- The API returns `system_key` with every category; the frontend uses it instead of names (`'Settle up'`).
- **Locked:** no rename, no type change, no delete (400 "This category is used by the app and can't be changed").
  Only the icon can change. Their names stay stable because converter configs and the import format use them.
- Migration **0006**: adds the column and sets the five keys on the existing rows by their current names.

## 2. Seeding

- The full default list is created only when the `categories` table is **empty** (a new database).
- On every start, each of the five system categories is created if no row has its key (with its default name, type
  and icon; if a row with that name exists without a key, it gets the key).
- So a renamed or deleted default category doesn't come back. New default categories in later versions need a data
  migration.

## 3. API (`backend/app/categories_api.py`, parents only for changes)

- `GET /categories` (unchanged access): each category now also has `system_key` (null for ordinary ones). Usage
  counts are a separate request, so this list stays light.
- `GET /categories/usage` (parents): `{category_id: {"transactions": n, "budgets": n, "planned_costs": n,
  "import_rules": n}}` for categories in use.
- `POST /categories`: name (trimmed, 1–50 characters, unique ignoring case → 400 "A category with that name already
  exists"), type `INCOME` | `EXPENSE` (`TRANSFER` → 400: transfers are system categories), optional icon (at most 8
  characters).
- `PUT /categories/{id}`: name, icon, type. System category: only the icon (anything else → 400 as above). Type
  change while used → 400 "Used by 12 transactions and 1 budget; its type can't change".
- `DELETE /categories/{id}`: system → 400; used → 409 "Used by 12 transactions and 1 budget" (only the non-zero
  counts, singular/plural); otherwise deleted.
- Children → 403 "Only parents can manage categories".

## 4. Screen: Settings → Categories (parents)

- An add form at the top: name, type (Income/Expense), icon (optional emoji).
- The list in three groups (Income, Expenses, Transfers), each row: icon, name, "used by …" in grey, 🔒 for system
  categories, Edit (inline: name, icon, type; for system categories only the icon) and Delete (confirm; hidden while
  used, with the reason as a tooltip).
- After a change the rest of the app picks up the new names on its next load (as with other Settings changes).

## Testing

- **Backend (`tests/test_categories.py`):** create (duplicate ignoring case, TRANSFER type, empty name, child 403);
  rename a seeded category; system category: rename/type/delete refused, icon allowed; type change blocked when used,
  allowed when unused; delete blocked with the counts message, allowed when unused; usage endpoint; seeding: a renamed
  and a deleted default don't come back, a missing system category is recreated; settle up, month check and import
  rules still find their categories after a non-system category is renamed.
- **Migration:** 0006 sets the five keys on an existing database; schema equals the models.
- **Browser test (`e2e/tests/categories.spec.ts`):** add a category, rename it, delete it; a system category shows 🔒
  without Delete.
- All existing tests and browser tests pass.

## Out of scope

- Merging two categories (moving their bookings), sub-categories, per-person categories.
