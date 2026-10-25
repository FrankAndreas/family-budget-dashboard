# Investments: the purchase booking, estimates, and tags in Analytics (step 1)

Approved by the user on 2026-10-25. Step 2 (leasing) follows in its own change; its design is at the end.

## Why

The dealer payment for the car shows up as a booking (bank import or receipt). Linked to the investment, the
receipt and warranty (Garantieschein) are one tap away from the investment, and Analytics can show what an area
(tag) costs: what was spent, and, apart from it, what is set aside each month for the next purchase.

## Step 1

**Purchase link**
- A booking linked "For investment" can be marked **"This is the purchase"**; one purchase per investment (marking
  another booking moves it). Both the plain booking form and the receipt form offer the link and the mark.
- Marking it fills the investment's price (the booking's amount) and purchase date (the booking's Swiss day); they
  can be changed by hand afterwards (e.g. a trade-in). Saving the booking again doesn't overwrite them; only marking.
- The purchase booking is not a follow-up cost (the price already holds it).
- The investment card shows "Bought on … for CHF …" with a 📎 per attachment of the purchase booking. Without a
  linked purchase: "≈ CHF … (estimated)".
- Unlinking the booking, or deleting it, takes the mark away; the price and date stay.

**Analytics per tag**
- **Spent**: receipt items with the tag (as today), plus bookings linked to an investment with that tag (the
  purchase in its month, follow-ups in theirs). A receipt linked to such an investment counts each of its items under
  the investment's tag too (items keep their own tags; an item counts once per tag).
- **Set aside**: the monthly set-aside of the active (not archived) investments with that tag, always per month,
  whatever the period. Personal: the owner's whole set-aside; common: each parent's share by the split.
- Tags with only a set-aside are listed too.
- Tag budgets count the linked bookings like Analytics' spent, never the set-aside.

**Data**: `transactions.asset_purchase` (boolean, migration 0017). Asset output gets `purchase` (booking id,
amount, date, attachments) or null. Marking needs write access to the investment. Export `transactions.csv` gets
`investment_purchase`; Analytics' `by_tag` rows get `set_aside`.

## Step 2: leasing (later)

- An investment is a **purchase** or a **lease**. A lease has: down payment and its date, monthly rate, term
  (months), final payment (buy-out), and the total lifespan in years.
- During the lease the monthly load is rate + final payment ÷ term (the buy-out is saved up by the end); replace by =
  lease end + the remaining lifespan.
- Down payment linked as the purchase; rates and buy-out linked as payments; all count under the tag as spent.
- After the buy-out (builder's call): the car goes on like a bought one; for the next car, the remaining lifespan
  sets aside what this one cost in total (down payment + all rates + buy-out).
- The lease end shows "due soon" on the group. A common lease's monthly load is divided by the split in the Common
  tab.
