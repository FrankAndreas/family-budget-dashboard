# Article rules for every receipt, learnt through suggestions

Status: worked out with the user in chat on 2026-10-29; waiting for their approval. Points marked "my call" are the
author's. Changes the Migros import (spec 2026-10-28), which so far saved its rules on import.

## Why

The article rules (article name → category and tags) only work for the Migros CSV import, and that import writes the
AI's answers into the rule set by itself. The user wants:

- the rules used for every receipt the AI reads (photo, forwarded mail, uploaded file), not only the CSV;
- **nothing in the rule set without their say**: the AI and the bookings only propose;
- after booking, a list of the new article ↔ category/tags pairs to correct and add, or to ignore when busy.

## What

**Using the rules**: when the AI has read a receipt, each line whose name matches an article rule (whole name,
ignoring case and surrounding spaces) gets the rule's category and tags; other lines keep the AI's proposal. The
receipt form shows "by article rule" on such a line (my call). The Migros import uses the rules as today.

**Suggestions instead of rules**: booking a receipt with lines (receipt form, scanned photo, mail, Migros import)
keeps a suggestion for each line whose article has no rule, or whose booked category or tags differ from its rule
(then the suggestion would change the rule; my call). A suggestion is the article name with the category and tags as
booked, so corrections made in the form or preview are in it. The same article is one suggestion; the latest booking
wins. Lines that only got the fallback (Groceries because the AI was off) make no suggestion (as before: the AI gets
another try). Discount lines make none.

The Migros import no longer saves rules: its "n new article rules" becomes "n new suggestions".

**The list**: Settings → Article rules gets "New suggestions (n)" above the rules: per suggestion the name, category
and tags (changeable), "changes the rule" when one exists, **Add** and **Ignore**, and **Add all**. Suggestions wait
until the user gets to them. Ignore deletes the suggestion; the article can come back with a later booking (my call).
After booking a receipt or importing, the success message says "n new article suggestions" with a link to the list
(my call).

**Who**: parents, as for the rules. A child booking a receipt makes no suggestions (my call: rules are the parents').

## Data

- New table `article_rule_suggestions` (id, name, name_key unique, category_id, created_at, updated_at) and
  `article_rule_suggestion_tags`; migration 0022, additive. Deleting a tag removes it from suggestions; a category in
  use by a suggestion: the suggestion goes with it (my call: it is only a proposal).
- API (parents): list, add (= make or update the rule, delete the suggestion; body may change category and tags),
  add all, ignore.
- Not in the export (only proposals; my call).

## Left to the builder

- Where suggestions are recorded (one function called by the receipt booking paths and the Migros import).
- How the receipt form marks "by article rule" (the AI draft can carry the source per item).
