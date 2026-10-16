# Money in integer cents, shown in CHF

Date: 2026-10-16. Status: draft, for review. Issues #41 and #34.

## Goal

- **#41:** every amount is stored as exact integer cents instead of a floating-point number; the unused
  `accounts.balance` column (balances are calculated since #39) is dropped.
- **#34:** the app shows money as Swiss francs, "CHF 1’234.50", instead of "$1234.50".

Nothing else changes for the user, the API, the import and export files or the converters: they keep using francs
with decimals (e.g. `84.3`).

Decided with the user: the API stays in francs (a column type converts at the database boundary); the format is the
Swiss one from `Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' })`.

## 1. Storage in cents

- New column type `Money` (`backend/app/money.py`, a SQLAlchemy `TypeDecorator` over `Integer`):
  - writing: francs → `round(value * 100)` cents (`None` stays `None`);
  - reading: cents → `cents / 100` francs as a float (`None` stays `None`);
  - comparisons in queries (e.g. `amount < 0`) convert the literal the same way.
- The seven amount columns use it: `transactions.amount`, `budgets.limit`, `assets.price`, `settlements.amount`,
  `planned_costs.amount`, `wishes.estimate`, `wishes.best_price`.
- `Account.balance` (the calculated sum): `SUM(amount)` and `COALESCE(…, 0)` keep the `Money` type, so the result is
  converted back to francs; it must not be wrapped in a function that drops the type (e.g. SQL `round`). The sum is
  exact in cents.
- `crud.to_cents` and the other roundings stay (harmless; they round francs before storing).

## 2. Migration 0004

- For each of the seven columns: `UPDATE … SET col = CAST(ROUND(col * 100) AS INTEGER)` (NULL stays NULL), then the
  column type becomes `INTEGER` (Alembic batch mode, which rebuilds the table in SQLite; data, keys and indexes are
  kept).
- `accounts.balance` is dropped.
- **Downgrade:** the columns become `FLOAT` again with `col / 100.0`; `accounts.balance` comes back, filled with the
  sum of each account's transactions.
- Rebuilding a table that others point to (e.g. `transactions`, referenced by `settlements`) fails while SQLite
  enforces links, and SQLite ignores `PRAGMA foreign_keys` inside a transaction. So `database_setup` runs the
  migrations with link checking **off for that connection** (set before the migration transaction starts), turns it
  on again afterwards, and the existing start-up check (`PRAGMA foreign_key_check`, logged) runs after the upgrade.
  This is the procedure SQLite's documentation gives for table rebuilds.

## 3. Display in CHF

- `frontend/src/finance.ts`: `money(value)` uses `Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' })`
  ("CHF 1’234.50", "CHF -22.10").
- Every amount shown uses `money()`: the places that build `$…` or call `toFixed(2)` for money directly (Dashboard,
  Analytics, Budgets, Common, Investments, Monthly costs, Yearly bills, Month check, Wishes) are switched. Chart axes
  keep plain numbers; chart tooltips use `money()`.
- Inputs (forms) keep plain numbers.

## Testing

- **Backend:**
  - `Money` round trip: `84.3`, `0.1`, `-22.1`, `None`; `0.1 + 0.2` booked as two transactions gives balance `0.3`
    exactly; a filter `amount < 0` in a query works.
  - **Migration:** a database at 0003 with float amounts (`84.3`, `-22.10`, `0.3`, a NULL estimate) upgraded to
    0004 has the right cents and no `accounts.balance`; downgraded to 0003 it has the francs again and balances
    filled; `compare_metadata` against the models is empty at head.
  - The full suite passes unchanged (the API is unchanged).
- **Browser tests:** expectations change from `$45.50` to `CHF 45.50` (with the Swiss separator where amounts reach
  thousands: `CHF 3’000.00`); all pass.

## Out of scope

- Other currencies, a language or format setting.
- Changing the API, the import format or the converters to cents.
