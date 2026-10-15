# Budget and accounts, kept apart; the month check

Date: 2026-10-15. Status: draft, for review. Builds on
`2026-10-14-bank-and-migros-converters-design.md` (same branch).

## Goal

The app answers two different questions, and they were getting mixed up:

- **Budget:** what does the family spend per category and month, against the plan?
- **Accounts (accounting):** does each account in the app match reality: the bank, the Migros clearing account?

Both stay, strictly apart on screen, but fed by **one set of bookings**. A purchase is entered once. It moves
an account balance and counts in its category. Transfers are pure accounting: they move balances but never
appear in the budget (already the case today).

The two sides meet in one place: the **month check** on clearing accounts. Money that went into the Migros
account but has no receipt is booked once a month as an **"Unknown expense"**. This family is not a company, so
there's no penny-exact reconciliation, just one booking for the gap.

Decided with the user: one set of bookings with two separate views (not separate records); a separate account
type "Clearing"; the reverse gap (more receipts than money) is booked as "Other Income". Issue #21 (reconcile to a
target balance) is replaced by the month check.

## 1. Two areas

- **Budget:** the tabs Budgets, Common, Yearly bills, Analytics. They work with categories and months and
  leave out transfers. No change.
- **Accounts:** the "📊 Overview" tab becomes **"🏦 Accounts"**: account cards with balances, the bookings of the
  selected account (transfers included), the manual entry form, and new: the month check (section 3). It stays
  the first tab.

## 2. Account type "Clearing"

- `AccountType` gets `CLEARING`, shown as "Clearing" in the account forms ("money in by transfer, out by
  receipts, 0 at the end of each month"). Existing accounts are unchanged. A Migros account created earlier as
  Bank is switched with the account's Edit button.
- The type only decides which accounts get the month check. Everything else treats it like a bank account.
- The JSON backup and its restore carry the new type.
- Not for the credit card as it stands: its purchases and the bill that pays them fall in different months, so
  its months never end at 0. A credit card check (by billing period) comes with the Viseca converter, if needed.

## 3. Month check

### What it shows

For each clearing account the user can see, the **completed months** (before the current month in Swiss time)
whose own bookings don't add up to 0:

```
Migros · September 2026   in 500.00   out 450.00   not tracked 50.00   [Book as Unknown expense]
Migros · August 2026      in 300.00   out 312.40   receipts over 12.40 [Book as Other Income]
```

- A month is the calendar month in `Europe/Zurich`. "in" is the sum of the month's positive bookings, "out" the
  sum of its negative ones, the difference is their sum.
- Each month is judged **on its own bookings**, not on the running balance. Booking one month's gap then never
  changes another month's, and the order in which months are booked doesn't matter.
- Differences below 0.01 count as 0. Months with nothing booked aren't listed.
- Months from the account's first booking up to last month; months that are fine aren't listed. If nothing is
  listed: "All months add up."

### The button

- Positive difference (money in, receipts missing): books an **expense of that amount** in the new category
  **"Unknown expense"**. Negative difference (receipts paid partly by gift card or Cumulus vouchers): books
  **income** of that amount in **"Other Income"**. Either way the month then adds up to 0.
- The booking: on that account, dated the month's last day at 12:00 UTC (same convention as a date-only import),
  description "Month check September 2026", reference `month-check:<YYYY-MM>`. In the budget it appears as an
  ordinary booking in that month and category.
- Nothing is booked automatically. Only someone with write access to the account sees the button.
- After booking, the month adds up and drops off the list. If it shows up again later (receipts for that month
  imported afterwards) while its month-check booking still exists (same reference on that account), the button
  is replaced by "Already booked; delete the month-check booking to book the new difference".

### API

- `GET /api/v1/accounts/{account_id}/month-check` → `[{month: "2026-09", money_in, money_out, difference,
  booked: bool}]`, newest first, only months with a difference. Read access to the account. 400 if the account
  isn't a clearing account.
- `POST /api/v1/accounts/{account_id}/month-check/{month}` (`YYYY-MM`) → the created transaction. Write access.
  Recomputes the difference on the server. Errors (400): not a clearing account; month not completed or not
  `YYYY-MM`; difference 0; already booked (409).
- The month-check booking is a normal transaction: it can be edited and deleted like any other.

## 4. Category

`seed.py` adds **"Unknown expense"** (`EXPENSE`, icon 🫥), created on start-up like the others. It's an ordinary
expense category: budgets, analytics and the import accept it.

## 5. Docs and issues

- `tools/converters/README.md` and the example config: create the Migros account as type Clearing; the gap is
  booked with the month check instead of by hand.
- The converters spec's references to #21 point to this spec.
- Close #21 with a note: replaced by the month check.

## Error handling

- Month check on a non-clearing account: 400 "Only clearing accounts have a month check".
- Month in the future or the current month: 400 "Only completed months can be checked".
- Difference 0: 400 "This month adds up already". Already booked: 409.

## Testing

- **Backend (pytest, `tests/test_month_check.py`):** months judged on their own bookings (a gap in August doesn't
  show in September); `Europe/Zurich` month boundaries (a booking at 23:30 Swiss time on 31 August counts for
  August); current month left out; positive gap → Unknown expense, negative → Other Income, month then adds up;
  second booking → 409, after deleting it bookable again; non-clearing account → 400; read access sees the list,
  write access needed to book; seed creates "Unknown expense"; account type Clearing created, edited, backed up
  and restored.
- **Frontend:** lint, type-check, build; browser test: Accounts tab, create a clearing account, book bookings in a
  past month, month check lists the gap, button books it, list says all months add up, the Budgets/Analytics tabs
  show the Unknown expense.

## Out of scope

- A month check for Cash or for the credit card.
- Automatic booking of the gap.
- Any change to the converters' output.
