# Family Budget export for analysis

Exported for **{user}** on {date}. It contains what {user} can see in the app: their own money, money
other family members share with them, and (for parents) the common budget, investments and planned costs.

## Format

- One CSV file per kind of data: UTF-8, comma-separated, `.` as decimal point, a header row.
- Timestamps are UTC in ISO 8601 (`2026-10-14T09:30:00Z`); plain dates are `YYYY-MM-DD`.
- An empty field means "no value".
- Every row has its own ID (`*_id`) and the IDs it refers to, plus the names for reading. Join on IDs:
  names can change and are not unique (two parents may both have an account called "Bank").
- All amounts are in CHF.

## Files

| File | One row per | Notes |
|---|---|---|
| `members.csv` | family member | `role` is `PARENT` or `CHILD`; `has_allowance` false = a child without own money, whose costs parents tag with `for_member` |
| `categories.csv` | category | `type` is `INCOME`, `EXPENSE` or `TRANSFER` |
| `accounts.csv` | account | `owner` is the member the account belongs to; `iban` if set (bank import finds the account by it); `balance` at export time |
| `transactions.csv` | booking | see below |
| `shared_expense_shares.csv` | parent and shared expense | how a shared expense is divided: `percent` and `share` (CHF) per parent; `payer` paid the full `amount` |
| `settlements.csv` | settle-up payment | `from` paid `to` to settle the common budget |
| `items.csv` | receipt item | the lines of a booking entered as a receipt; see below |
| `tags.csv` | tag | what items are for (e.g. "Velo"), across categories |
| `budgets.csv` | budget | spending limit per `category` **or** per `tag`, and `period` (`MONTHLY` or `YEARLY`) |
| `splits.csv` | parent and split | a named ratio for dividing common costs, e.g. "Equal" 50/50 |
| `investments.csv` | investment | long-lived purchase; `age_years`, `replacement_due`, `monthly_set_aside` (price spread over the lifespan), `follow_up_costs` (linked expenses), `total_cost`, `cost_per_year` are calculated on the export day |
| `planned_costs.csv` | planned cost | yearly bills (`frequency` `YEARLY`, `due_month` 1-12, `next_due`) and common monthly costs; `monthly` is the monthly equivalent; `owner` for a personal cost, `split` for a common one |
| `wishes.csv` | wish | things to buy: `owner` or `split` (common), `estimate`, the best offer found, `price` (best price, else estimate), `position` in the owner's list, `family_position` in the parents' family plan (empty = not in it), `bought_on` |

### transactions.csv

- `amount` has a sign: income is positive, expenses are negative.
- `category_type` `TRANSFER` marks settle-up payments between parents. They move money between the parents'
  accounts and are **neither income nor spending**: exclude them when summing.
- A shared expense (`split` set) appears **in full** in the payer's transactions, because that is what left
  their account. Each parent's part is in `shared_expense_shares.csv` (join on `transaction_id`).
- `for_member` is the child an expense was for; `investment` the investment it belongs to (purchase, repair,
  service); `reference` is the ID an import tool gave the source receipt.

### items.csv

- A booking entered as a receipt has **items**: one row per line, joined on `transaction_id`. The booking's
  `amount` in `transactions.csv` is minus the sum of its items, and its `category` is the one with the largest
  items; for spending per category, use the items instead of such bookings.
- `amount` is positive for a cost and negative for a discount or deposit refund.
- `tags` lists the item's tags, separated by `;`. An item with several tags belongs **in full** to each of them,
  so totals per tag overlap: never add them up. `person` is whom the item was for.

## Examples (pandas)

```python
import pandas as pd

t = pd.read_csv("transactions.csv", parse_dates=["date"])
# t holds every account you can see; for only your own: t = t[t.owner == "{user}"]

# Spending per month and category, without settle-up transfers
spending = t[t.category_type == "EXPENSE"].assign(month=t.date.dt.strftime("%Y-%m"))
print(spending.pivot_table(index="month", columns="category", values="amount", aggfunc="sum").abs())

# Each parent's share of the shared expenses per month
s = pd.read_csv("shared_expense_shares.csv", parse_dates=["date"])
print(s.assign(month=s.date.dt.strftime("%Y-%m")).groupby(["month", "member"]).share.sum().unstack())

# Investments due for replacement within the next two years
i = pd.read_csv("investments.csv", parse_dates=["replacement_due"])
print(i[i.replacement_due < pd.Timestamp.today() + pd.DateOffset(years=2)][["name", "replacement_due", "price"]])
```

To import new transactions (for example from receipts), see the import format in the app's repository:
`docs/import-format.md`, or Settings → Data Management → Import transactions.
