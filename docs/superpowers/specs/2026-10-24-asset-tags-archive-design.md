# Investments: tags, groups and archive

Approved by the user on 2026-10-24.

## Why

The Investments (Anschaffungen) list is one long grid. A family wants to see what an area costs (Mobilität: car and
bikes; Sport: skis), fold the areas it doesn't care about right now, and take things that are gone (sold, scrapped)
out of the totals without deleting their history.

## What

**Tags**
- An investment has at most **one tag**, from the family-wide tags used on receipt items. One tag keeps every
  investment in exactly one group, so group totals never count anything twice.
- The investment form has a tag select (none, the existing tags, "+ New tag…" which asks for a name and creates it).

**Groups**
- The active investments are grouped by tag, plus a group "No tag" for the rest. Groups are sorted by monthly
  set-aside, largest first; inside a group, by replacement date, soonest first.
- Each group folds. Its header: icon, name, count, **CHF … / month**, CHF … so far, and a "due soon" marker when an
  item in it is due for replacement within a year (or already due).
- Opened, a summary row above the items: purchase price, follow-up costs, cost per year, next replacement.
- Open/folded is remembered in the browser: folded on a phone (< 768 px), open on wider screens, like the Settings
  sections.
- A grand total line above the groups: the same figures for all active investments.
- The existing filter (all / mine / common / others) applies before grouping.

**Archive**
- "Archive" on an item asks for the date it left (default today). An archived item leaves every total and the
  monthly set-aside, including the Common tab (so the other parent's share drops too).
- Archived items are in a folded section "Archived (N)" at the bottom, with their costs so far frozen at the archive
  date (age and cost per year computed at that date).
- An archived item is not offered under "For investment" when booking an expense; bookings already linked keep their
  link, and editing such a booking keeps it.
- "Restore" undoes it. Nothing is deleted.

**Not part of this:** tag budgets and Analytics don't count investments.

## Data

- `assets.tag_id` (FK tags.id, nullable) and `assets.archived_on` (date, nullable), migration 0016.
- Deleting a tag clears it on investments (they move to "No tag").
- API: `tag_id` in the investment body (unknown tag → 400). `POST /assets/{id}/archive` `{"archived_on": date}` and
  `DELETE /assets/{id}/archive` (restore), both need write access to the item. Archived output: `monthly_set_aside`
  0, `shares` {}, `is_due` false.
- Linking an expense to an archived investment → 400, unless the booking already links to it.
- Export `investments.csv` gets `tag_id`, `tag`, `archived_on`.

## Builder's calls

- Bulk import keeps matching investments by name, archived ones too (an import names them explicitly).
- The archive date can't be before the purchase date nor in the future.
