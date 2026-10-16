# Budgets and analytics calculated on the server

Date: 2026-10-16. Status: draft, for review. Issue #30.

## Goal

Budgets and Analytics load every transaction of the scope's accounts into the browser (500 per request, account by
account, `fetchTransactionsForUsers`) and add them up there, in the browser's time zone. That gets slower with every
import and counts months differently from the server (the month check uses Swiss time).

After this change the server returns the finished numbers, in Swiss time (`Europe/Zurich`), with its own access rules.
The screens look and behave as before.

Decided with the user: the numbers and charts stay the same; only where they are calculated changes.

## Scope and rules (unchanged)

- A **scope** is one person's money: the caller's own, or that of someone whose money the caller may see
  (`privacy.check_user_access`; view rights are enough to read). Only that person's accounts count.
- **Transfers** (category type `TRANSFER`: Transfer, Settle up) never count.
- **Income** = transactions in `INCOME` categories, **expenses** = transactions in `EXPENSE` categories, both as
  positive amounts, rounded to cents.
- Months and days are calendar months and days in `Europe/Zurich`. Stored dates are naive UTC.
- "Today" comes from one function (`reports.today()`, Swiss date) that tests can replace.

## 1. Budgets: spending in `GET /budgets`

`GET /budgets?user_id=` (unchanged access) returns each budget with two more fields:

- `spent`: expenses of the budget owner's accounts in the budget's category, in the current Swiss month (`MONTHLY`)
  or calendar year (`YEARLY`);
- `percentage`: `spent / limit * 100`, rounded to one decimal (0 when the limit is 0).

`POST`/`PUT` responses of budgets get the same fields.

## 2. Analytics: `GET /reports/summary`

Query: `user_id` (optional, default the caller), `range` = `month` | `3months` | `year` | `all` (default `month`).

- `month`: from the 1st of the current Swiss month; `3months`: from the 1st of the month two months back; `year`: from
  1 January; `all`: no lower bound. No upper bound (future-dated bookings count, as today).

Response:

```json
{
  "range": "month",
  "income": 5200.0,
  "expenses": 3150.4,
  "by_category": [{"category_id": "…", "name": "Groceries", "amount": 820.5}],
  "by_child": [{"member_id": "…", "name": "Kim", "amount": 120.0}],
  "months": [{"month": "2026-05", "income": 5200.0, "expenses": 3010.0}],
  "days": [{"date": "2026-10-01", "income": 0.0, "expenses": 64.3}]
}
```

- `income`, `expenses`, `by_category`, `by_child` cover the selected range.
- `by_category`: expense categories with spending in the range, largest first.
- `by_child`: expenses tagged with a dependent child (`member_id`), per child, largest first; children without any are
  left out. Only for a parent's scope (empty for a child's own scope, as today).
- `months`: always the last 6 Swiss months including the current one, oldest first, every month listed (0 when none).
- `days`: always every day of the current Swiss month, in order (0 when none).
- Errors: `range` not one of the four → 422; no access to `user_id` → 403; unknown user → 404.

Implementation: `backend/app/reports.py` (router + pure functions). The database selects the scope's non-transfer
transactions from the earliest date needed (the range start, or the 6-months start, whichever is earlier; all for
`all`), using the `(account_id, date)` index; grouping into Swiss months and days is done in Python.

## 3. Frontend

- `BudgetManager.tsx` shows `spent` and `percentage` from `GET /budgets`; it no longer loads transactions or categories
  for the calculation.
- `Analytics.tsx` loads `GET /reports/summary` for the scope and range (again when either changes) and shows the
  numbers; month labels (`MMM`) and day labels (`MMM dd`) are formatted from the ISO keys; "net"/"savings" =
  income − expenses, as now.
- `fetchTransactionsForUsers` in `api.ts` is removed (no other users).

## Testing

- **Backend (`tests/test_reports.py`):** income/expenses/by_category with known bookings; transfers excluded; each
  range's start (with a fixed "today"); a booking at 23:30 Swiss time on 31 August counts for August and for that day;
  `months` has 6 entries with zeros; `days` covers the month; `by_child`; another person's scope with view rights works,
  without rights 403; invalid range 422. Budgets: `spent` and `percentage` for monthly and yearly budgets, other
  categories and other people's accounts not counted.
- **Browser test (`e2e/tests/reports.spec.ts`):** bookings via the API, then the Budgets tab shows the spent amount and
  Analytics shows income and expenses for "This Month".
- The existing browser tests pass unchanged.

## Out of scope

- New reports (several people combined, year-over-year).
- Paging the transaction list on the Accounts tab.
