# Separate parent finances, common budget, investments and yearly bills

Date: 2026-10-14. Status: draft for review.

## Goal

Each parent manages their own money. Costs the parents share are handled in a **common budget**:
who paid, how it's divided, who owes whom, and what each parent contributes per month. Two new
tabs plan for big, rare costs: **investments** (TV, fridge, car, MTB) and **yearly bills**
(water, power, insurance).

Decided with the user:
- Common budget answers both "who owes whom" (from actual payments) and "monthly share per parent"
  (from planned costs).
- Splits are 2–4 preset named ratios (e.g. "Equal 50/50", "By income 70/30").
- A shared cost is entered as a normal expense on the paying parent's own account.
- A parent's finances are private by default; a parent can share them with the other parent as
  **view** or **edit** (delegation).
- Investments: replacement planning, inventory (notes), and total cost of ownership.
- Yearly bills: due-date overview and monthly set-aside (no "mark as paid" for now).

Unchanged: children with own allowance (Jugendlohn) and their privacy toggle; dependent children
(no login) whose costs are tagged; 4-digit PINs; parents manage the family in Settings.

## Data model

New and changed tables (SQLite; new columns via `migrate.NEW_COLUMNS`, new tables via `create_all`).

**`shares`** — a parent shares their own finances with another parent.
`owner_id`, `grantee_id` (both parents), `level` = `VIEW` | `EDIT`. One row per pair; no row = none.

**`splits`** — preset ratios between the parents, at most 4.
`id`, `name` (unique), `shares` JSON `{parent_id: percent}`; percents are whole numbers ≥ 0,
summing to 100, one entry per active parent.

**`transactions`** — new nullable columns:
- `split_id`: set = shared expense. Only on an expense, only on a parent's account.
- `split_shares` JSON: a copy of the split's percents at the time of the expense, so editing a
  split later doesn't change past balances.
- `asset_id`: the investment this expense belongs to (purchase or follow-up cost).

**`settlements`** — "settle up" records: `from_user_id`, `to_user_id`, `amount`, `date`, and the
two transactions it created (`from_transaction_id`, `to_transaction_id`).

**`planned_costs`** — `name`, `category_id`, `amount` (positive), `frequency` = `MONTHLY` | `YEARLY`,
`due_month` (1–12, required for yearly), `owner_id` (a parent) **or** `split_id` (common), `notes`.
Monthly planned costs are always common (personal monthly costs are covered by budgets).

**`assets`** (investments) — `name`, `price`, `purchase_date`, `lifespan_years` (> 0),
`owner_id` **or** `split_id`, `notes` (warranty, serial number, ...).

**Categories** — new type `TRANSFER` next to `INCOME` and `EXPENSE`, and a seeded category
"Settle up" (added by name on startup, also to existing databases). Transfers change account
balances but count in neither income, expenses, budgets nor analytics.

## Access rules (`privacy.py`)

- A parent sees and edits their own accounts, transactions and budgets.
- Another parent's: only with a share — `VIEW` = read only, `EDIT` = everything the owner can do
  with their accounts, transactions and budgets. Never the owner's PIN or share settings.
- The household scope goes away: budgets belong to the parent who created them (existing
  `user_id`), and `budget_owner_ids` returns just the owner.
- Children: unchanged (parents see an allowance child unless privacy is on; never edit).
- Dependent children stay visible to all parents; any parent can tag their own expenses with them,
  shared or not.
- Common budget, splits, planned costs and assets: every parent sees and manages all common items
  and their own personal ones; personal items of another parent follow the share level.
  Children don't see these tabs.

## Calculations

All amounts rounded to cents.

- **Who owes whom:** for each shared expense of amount A paid by P, every other parent i owes P
  `A × split_shares[i] / 100`. Settlements reduce it. With two parents this is one number
  ("Anna owes you CHF 230"); the API returns a net amount per parent so a third parent still works.
- **Settle up:** amount (prefilled with the full balance), from-account (payer's) and to-account
  (receiver's). Creates two `TRANSFER` transactions and a settlement. Deleting the settlement
  deletes both transactions.
- **Monthly equivalent:** monthly planned cost = amount; yearly = amount / 12;
  asset = price / (lifespan_years × 12).
- **Monthly share per parent** (Common tab): sum of the monthly equivalents of all common planned
  costs and common assets, each multiplied by the parent's percent in its split.
- **Yearly bills:** next due date = the coming occurrence of `due_month`; "due soon" = within
  the next 2 months. Total per year and monthly set-aside, per parent for common bills.
- **Asset:** age, replacement due = purchase_date + lifespan, "due" once past; total cost =
  price + linked expenses; cost per year = total cost / max(age in years, 1).

**Decision to confirm:** budgets and analytics of a parent count the **full** amount of a shared
expense they paid (it's what left their account); their share appears only in the Common tab.
Alternative: count only the parent's share there. Full amount is simpler and matches the account
balance.

## Screens

Tabs: Overview · Budgets · Common · Investments · Yearly bills · Analytics · Settings
(children: Overview · Budgets · Analytics · Settings). The tab bar scrolls sideways on a phone.

- **Whose-money selector:** you, the other parent if shared with you (banner "Viewing Anna's
  finances", edit buttons hidden for `VIEW`), allowance children as today.
- **Expense form:** new "Shared" dropdown (default "Not shared", then the splits) and optional
  "For item" (assets). Shared only for parent accounts and expenses.
- **Common:** balance card with Settle up; monthly overview (common planned costs and assets with
  monthly amount and total per parent); recent shared expenses (payer, split, each share);
  manage splits (2–4, name + percent per parent).
- **Investments:** cards (name, owner, age bar "4 of 8 years", replacement due, monthly
  set-aside); detail with linked expenses, total cost and cost per year; filter mine / common /
  other parent's (if shared); add / edit / delete.
- **Yearly bills:** list sorted by next due date, due soon highlighted, total per year, monthly
  set-aside (per parent for common bills); add / edit / delete (name, category, amount, due month,
  owner: me or common + split). Monthly planned costs are managed in the Common tab.
- **Settings → Family:** "Share my finances with Anna: none / view / edit" for parents.

## Rules and edge cases

- Validation (400): split percents not summing to 100 or missing a parent; a 5th split; shared
  on income, on a child's account, or with an unknown split; planned cost or asset with both or
  neither of owner and split; a monthly cost without split; yearly without due month; lifespan ≤ 0; negative amounts.
- A split used by planned costs or assets can't be deleted (409 "In use by …"); shared expenses
  keep their snapshot, so deleting a split they used is fine.
- Deleting an asset unlinks its expenses (they stay as normal expenses).
- Only one parent: Common tab explains that sharing needs a second parent; splits can't be created.
- A new parent added later gets 0 % in existing splits until a parent edits them.
- Deactivating a parent: their open balance stays visible until settled.
- Existing data: accounts and budgets stay with their current owner; no shares are created, so
  parents no longer see each other until they share.

## Testing

- Backend (pytest, `tests/test_common.py`, `test_assets.py`, `test_planned_costs.py`,
  `test_shares.py`; update `test_family.py` for the removed household scope): access per share
  level, split validation and snapshot, balance and settlement math (incl. rounding and three
  parents), monthly share, due dates across the year boundary, asset cost figures, migration of an
  existing database.
- Smoke test: add a shared expense and check the balance.
- Frontend: lint, type-check, build; Puppeteer flow: share view → read-only banner, shared expense
  → balance → settle up, add asset and yearly bill.

## Out of scope

Marking yearly bills as paid / bill history, joint accounts, splits among children, per-child
budget limits, notifications for due bills.
