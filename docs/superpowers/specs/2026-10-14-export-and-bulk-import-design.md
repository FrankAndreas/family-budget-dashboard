# Export for analysis and bulk import of transactions

Date: 2026-10-14. Status: draft, for review.

## Goal

Two one-way data paths, no round trip:

1. **Export for analysis:** a ZIP of CSV files plus a README, for Jupyter/pandas or a local LLM agent.
2. **Bulk import:** an external tool (not built yet; e.g. a local LLM reading receipts) writes a file of
   new transactions in a format this app defines; the app checks it, shows a preview, and books it.

Decided with the user:
- Formats are defined by the app; the external tool will be built to produce them.
- The import accepts CSV and JSON with the same fields; names instead of IDs.
- An optional `reference` per row (the tool's own receipt ID) makes repeated imports recognisable.
- A JSON Schema is offered so local LLMs (Ollama, llama.cpp structured output) produce valid files.
- Database migration (e.g. SQLite → PostgreSQL) is out of scope; it will be an admin script later.

Unchanged: the JSON backup export and its import (Settings → Data Management) stay as they are, except
that transactions carry the new `reference` field. The old single-table CSV export is replaced by the ZIP.

## Data model

`transactions.reference`: new nullable `VARCHAR` (via `migrate.NEW_COLUMNS`), at most 200 characters.
Set by the bulk import; optional in `TransactionCreate` (so a JSON backup keeps it) and returned in
`Transaction`. Not shown or edited in the UI.

## 1. Export for analysis

`GET /api/v1/export/analysis.zip` (any logged-in user) returns `budget-analysis-YYYY-MM-DD.zip`.

**Scope = what the user can see in the app**, using the existing access rules:
- accounts, their transactions and budgets: users with any access level (`privacy.access_level` not
  None) — own, shared with view or edit, children as today;
- common data (splits, settlements, shared-expense shares, investments, planned costs): parents only,
  filtered with `visible_owner` like the tabs. For a child these files contain only the header.

**Files** (UTF-8 without BOM, comma separator, `.` decimal point, header row, RFC 4180 quoting,
dates ISO 8601: timestamps in UTC as `2026-10-14T09:30:00Z`, plain dates as `2026-10-14`; empty
field = no value; each row has its ID and the IDs it refers to, plus names for reading):

| File | Columns |
|---|---|
| `members.csv` | `member_id, name, role, has_allowance, is_active` (only listable members) |
| `categories.csv` | `category_id, name, type` (`INCOME` / `EXPENSE` / `TRANSFER`) |
| `accounts.csv` | `account_id, name, type, owner_id, owner, balance` |
| `transactions.csv` | `transaction_id, date, account_id, account, owner_id, owner, category_id, category, category_type, amount, description, for_member_id, for_member, split_id, split, investment_id, investment, reference` |
| `shared_expense_shares.csv` | `transaction_id, date, payer_id, payer, amount, member_id, member, percent, share` (one row per parent per shared expense; same set as the Common tab) |
| `settlements.csv` | `settlement_id, date, from_id, from, to_id, to, amount` |
| `budgets.csv` | `budget_id, owner_id, owner, category_id, category, limit, period` |
| `splits.csv` | `split_id, name, member_id, member, percent` (one row per parent per split) |
| `investments.csv` | `investment_id, name, owner_id, owner, split_id, split, price, purchase_date, lifespan_years, age_years, replacement_due, monthly_set_aside, follow_up_costs, total_cost, cost_per_year, notes` |
| `planned_costs.csv` | `planned_cost_id, name, category_id, category, amount, frequency, due_month, next_due, monthly, owner_id, owner, split_id, split, notes` |
| `README.md` | data dictionary (below) |

`amount` in `transactions.csv` is signed as stored: income +, expense −, transfers (Settle up) as booked.
Computed columns use the same functions as the app (`asset_out`, `planned_cost_out`).

**README.md** (static text in the backend, with the export date and user name filled in): what each
file and column means; currency CHF; the sign convention; "exclude `category_type == TRANSFER` when
summing spending"; shared expenses appear in full in the payer's transactions, the shares are in
`shared_expense_shares.csv`; how files join; 3 pandas examples (spending per month and category
without transfers; my share of shared expenses; investments due for replacement in the next 2 years).

## 2. Bulk import

### Format

One object per transaction. CSV with a header row, or JSON `{"transactions": [ {...}, ... ]}`.

| Field | Required | Rules |
|---|---|---|
| `date` | yes | `YYYY-MM-DD` (booked at 12:00 UTC, so it stays on that day in Switzerland) or ISO 8601 with time (offset honoured; no offset = UTC, as today) |
| `account` | yes | name of an account the user can **write** (own, or shared with "view and manage") |
| `owner` | no | the account owner's name, only needed when two writable accounts have the same name |
| `category` | yes | category name; `TRANSFER` categories are rejected; the category decides the sign |
| `amount` | yes | number > 0, `.` as decimal point (JSON: number or string) ; rounded to cents |
| `description` | no | text, at most 200 characters |
| `for` | no | name of a child without own allowance (only on a parent's account) |
| `shared` | no | split name (only expenses on a parent's account) |
| `item` | no | investment name the user can see |
| `reference` | no | the tool's ID for the source (file name, hash, ...), at most 200 characters |

- Matching of all names: case-insensitive, surrounding spaces ignored. Unknown or ambiguous names are
  errors; nothing is ever created by the import.
- `account` without `owner`: the user's own account with that name wins; otherwise the single writable
  account with that name; several → error "Several accounts are called X; add `owner`".
- The same business rules as the form apply (reuse `check_member_tag`, `check_shared`, `check_asset`).
- CSV: UTF-8 (a BOM is tolerated), separator `,` or `;` (detected from the header line), header names
  case-insensitive, unknown columns ignored. JSON: unknown fields ignored.
- Limits: file ≤ 1 MB, ≤ 1000 rows; otherwise 400 with a message.

### Duplicates

A row is a **duplicate** if
- its `reference` equals the `reference` of an existing transaction on an account the user can see, or of
  an earlier row in the same file; or, for rows without `reference`,
- an existing transaction on the same account has the same day, amount and category.

Duplicates are not errors; they are shown and skipped unless the user ticks them.

### API

- `POST /api/v1/import/preview` (multipart `file`) → `{"rows": [{"line", "status": "ok" | "duplicate" |
  "error", "errors": [..], "duplicate_of": transaction_id | null, "date", "account", "owner", "category",
  "amount", "description", "for", "shared", "item", "reference"}], "ok": n, "duplicates": n, "errors": n}`.
  `line` = CSV line number (header = 1) or JSON array index + 1. Nothing is stored.
- `POST /api/v1/import` (multipart `file` + `include_duplicates`: list of line numbers) re-checks the
  file; any error → 400 with the same rows; otherwise books all ok rows plus the ticked duplicates in
  **one database transaction** (all or nothing) and returns `{"imported": n, "skipped": n}`.
- `GET /api/v1/import/schema` → a JSON Schema (draft 2020-12) of the JSON format **for this user**:
  `account`, `category` (non-transfer), `for`, `shared` and `item` carry `enum`s of the names valid for
  them, every field has a `description`. A local LLM can use it as its output format directly.
- `GET /api/v1/import/template.csv` → header plus two example rows.

### Screen (Settings → Data Management)

- **Export:** "Export for analysis (.zip)" and the existing "Backup (JSON)".
- **Import transactions:** short explanation, links "CSV template" and "JSON Schema (for AI tools)",
  file picker → preview table (line, date, account, category, amount, description, status). Errors in
  red with their reasons; duplicates with an unticked checkbox and "already booked on <date>". Button
  "Import N transactions", disabled while there are errors. After success: message with the count and
  the lists reload.
- **Restore backup (JSON):** the existing import, unchanged.

## Rules and edge cases

- A child with own allowance can export and import their own data; a dependent child can't log in.
- `VIEW` access: included in the export, never an import target.
- Rows booked by the import change account balances like any transaction.
- A file with only duplicates and none ticked imports nothing and says so.
- Format documentation lives in `docs/import-format.md` (same content as the field table above, with a
  CSV and a JSON example), linked from the README.

## Testing

- Backend pytest `tests/test_export.py`: ZIP contains all files with the documented headers; scope per
  access level (VIEW included, NONE excluded, child privacy hides the child, child user gets empty common
  files); amounts, transfers and shared-expense shares; computed investment columns.
- Backend pytest `tests/test_import.py`: CSV with `,` and `;`, BOM, JSON; name matching and `owner`
  disambiguation; every validation error with its line; date-only at 12:00 UTC; duplicates by reference
  (DB and within file) and by day/amount/category; `include_duplicates`; all-or-nothing on error; VIEW
  account rejected; limits; schema enums per user; migration adds `reference` to an existing DB.
- Frontend: lint, type-check, build; Puppeteer: import a CSV with one error (blocked), fix it, preview a
  duplicate, import; download the ZIP and read it with pandas in the scratch venv.

## Out of scope

Receipt images, creating accounts/categories/members during import, import into VIEW-shared accounts,
importing budgets/investments/bills, Excel files, database migration.
