# Database foundation: migrations, enforced links, calculated balances

Date: 2026-10-16. Status: draft, for review. Issue #29.

## Goal

The database (SQLite, live on the NAS with real data) can't evolve safely and doesn't protect itself:

- no migrations: start-up runs `create_all` plus a hand-kept list of new columns (`app/migrate.py`);
- the links between tables are declared (`FOREIGN KEY … REFERENCES` is in every table's DDL) but SQLite never checks
  them, so a missed cleanup leaves hidden orphans;
- `Account.balance` is stored and updated step by step in four places; one missed path would leave it wrong for good.

After this change: schema changes are migration files that the app applies itself on start-up; SQLite enforces the
links; an account's balance is the sum of its transactions. Money in cents is a later, separate step.

Decided with the user: Alembic; the existing hand-written cleanup stays and is now backed by enforced links; balances
are calculated, not stored (instead of a stored balance plus a check).

## 1. Alembic migrations

- `alembic==1.20.0` in `backend/requirements.txt`.
- Migrations live in the app package, `backend/app/migrations/` (`env.py`, `versions/`), so the Docker image (which
  copies `backend/app`) needs no change. `backend/alembic.ini` points to them (`script_location = app:migrations`)
  for developers (`alembic revision --autogenerate -m "…"`).
- Revisions:
  - **0001 baseline**: creates today's schema exactly (all tables, columns, foreign keys, the unique constraint on
    `categories.name`), written out explicitly (no `create_all` in a migration).
  - **0002 repair links**: clears optional links that point nowhere: `transactions.member_id`, `split_id`,
    `asset_id` (to NULL). Nothing is deleted.
  - **0003 indexes**: `transactions(account_id, date)` and `transactions(reference)`.
- **Start-up** (`app/database_setup.py`, called from `main.py` instead of `create_all` and `add_missing_columns`):
  1. Database **without tables** → `upgrade head`.
  2. Tables but **no `alembic_version`** (every database made before this change, e.g. the NAS) → first the old
     catch-up one last time (`create_all` + the `NEW_COLUMNS` list, moved into this module), so even an older
     database reaches the baseline; then `stamp 0001`; then `upgrade head`.
  3. Otherwise → `upgrade head`.
  Then it runs `PRAGMA foreign_key_check` and logs each table with rows whose links point nowhere (count and table),
  as a warning. The app starts anyway.
- `app/migrate.py` is removed (its column list moves into the catch-up step of `database_setup.py`).
- Tests keep creating tables with `create_all` (fast). Separate tests run the real migrations (section 4).

## 2. Enforced links

- Every new SQLite connection runs `PRAGMA foreign_keys=ON` (SQLAlchemy `connect` event on the engine in
  `database.py`).
- The existing cleanup code stays as it is (`crud.delete_user`, splits in use, investments, wishes). With enforcement,
  a cleanup that is missed or done in the wrong order fails with an error instead of leaving an orphan. The full test
  suite runs with enforcement on, so the existing tests check every delete path.
- If a delete path fails under enforcement, it gets fixed in this change (order of deletes, or the missing cleanup),
  with a test.

## 3. Calculated balances

- `Account.balance` becomes a calculated attribute: the sum of the account's transactions rounded to cents
  (SQLAlchemy `column_property` with a correlated `SUM`, `COALESCE` to 0). Every place that reads `account.balance`
  (account list, create, edit, the export's `accounts.csv`) keeps working unchanged, and the API's `balance` field
  stays.
- The stored column stays in the table (mapped under another attribute name, no longer written or read) and is
  dropped with the cents step.
- Removed: the balance updates in `crud.create_transaction`, `update_transaction`, `delete_transaction`, the
  settle-up code in `common_api.py`, and `balance=0.0` in `crud.create_account`.

## 4. Testing

- **Migrations on an empty database** produce exactly the models' schema: Alembic's autogenerate comparison
  (`compare_metadata`) finds no differences.
- **An old database** (made with `create_all` without `alembic_version`, plus an older one missing a recent column
  and table) is caught up, stamped and upgraded on start-up; its data is still there.
- **Repair migration:** a transaction whose `member_id`, `split_id` or `asset_id` points nowhere has it cleared; a
  valid one is untouched.
- **Start-up check** logs a table with a broken link (caplog).
- **Enforcement on:** inserting a transaction for an account that doesn't exist fails; the whole existing suite
  passes with enforcement on.
- **Balances:** after create, edit (amount and category), delete, import, settle up and undo, the balance equals the
  sum of the transactions; a new account has balance 0; existing balance tests keep passing.
- Browser tests (`e2e/`) pass unchanged.

## Rollout

`nas-update.sh` backs up the database before updating and keeps the previous images. The new version upgrades the
database on its first start (catch-up, stamp, repair, indexes). To go back: the previous image plus the backup.

## Out of scope

- Money in integer cents and dropping the stored `balance` column (a separate issue after this one).
- `ON DELETE` rules in the schema (would need table rebuilds in SQLite); the cleanup stays in code.
- Postgres or any other database.
