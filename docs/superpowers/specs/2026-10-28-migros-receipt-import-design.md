# Migros receipts from the Cumulus CSV export

Status: worked out with the user in chat on 2026-10-28; waiting for their approval. Points marked "my call" are the
author's.

## Why

The family shops at Migros every week, with one shared Cumulus card. Migros offers all receipts of a period as one
CSV ("Kassenbeleg" export: every article of every receipt). Today that file only goes through the command-line
converter `tools/converters/migros.py`, which books one line per receipt and category on a Migros clearing account:
the articles are lost, and the bookings don't meet the bank payments. Photographing or forwarding each receipt works
but is one receipt at a time, and the AI has to read every image.

## What success looks like

Once a month: export the CSV from Cumulus, upload it in the app like a bank statement, check a preview with one row
per receipt, import. Each receipt is then one booking with its articles as lines, sitting on the bank payment that
paid it (TWINT or debit card), every article with a category and tags. Next month most articles are known without
the AI.

## Goals

- Upload the CSV as it comes from Migros, in the existing import (Settings → Data Management → Import); the app
  recognises the format.
- One booking per receipt, every article its own line.
- A category and tags per article: article rule first, then the AI, then a fallback; what was booked becomes the rule.
- The receipt meets its payment: put onto the bank booking that paid it, or booked so the later bank import finds it.
- Never twice: not when the same month is uploaded again, not when both parents upload it, and not silently on top of
  a receipt already photographed or forwarded.

## Non-goals

- Other shops' exports (Coop, Galaxus): the design leaves room, nothing is built for them.
- "For whom" (a child) per article from rules: can be set by hand on a line after importing.
- Using the article rules when the AI reads a photographed receipt (a sensible later step).
- Removing `tools/converters/migros.py`: it stays, with a note in its README that the app now reads the file
  directly (as for `bank.py`).

## Anti-goals

- A wrong AI guess that sticks for every future receipt.
- A receipt booked twice, or a bank payment left with a twin booking next to it.
- Real receipts in the repository: it is public. Tests use invented articles and stores only.

## The file

Header (`;`-separated, as exported):

```
Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz
```

- **A receipt** = the rows with the same Datum, Zeit, Filiale, Kassennummer and Transaktionsnummer.
- **Umsatz** is the line's amount as paid (after the discount); **Aktion** is the discount already taken off
  (shown nowhere, my call). **Menge** may be a weight in kg (0.424); it is not needed for the amount.
- **Till corrections**: the same article cancelled and scanned again (Karotten 2 / −2 / 1) are added up per article
  name within a receipt; an article that comes to 0 disappears.
- **Cumulus vouchers** (`CUMULUS BON 20.-`, Umsatz −20.00): one line per voucher with its negative amount (a
  discount), category of the receipt's main category (my call: as the existing "Difference" line).
- **Points-only rows** (Umsatz 0: `Bonus-Coupon 2x`, `CUM10x Pkt …`, `+3x Pkt. …`): dropped.
- The receipt's total = the sum of its lines (vouchers included) = what was paid.
- The booking's date and time are the receipt's (Swiss time), its description "Migros <Filiale>" (my call).

## Categories and tags per article

In this order, per distinct article name in the file:

1. **Article rule**: a new kind of rule, matching the **whole article name, ignoring case** (not "contains", unlike
   the bank's import rules: "Rind" must not catch "Rinderbouillon"). It gives a category and any number of tags.
2. **The AI**, for the names without a rule, when the receipt AI is set up: one text call per file with the article
   names and the family's expense categories and tag names, counted as one read toward the importer's hourly
   limit. Only article names are sent, never stores, dates or amounts. Up to `MAX_TEXTS` (200) names per call;
   more → the rest fall back (my call, as the bank import).
3. **Fallback**, when the AI is off, failing, over the limit or unsure: *Groceries*, no tag.

**Rules learnt on import** (the user's wish, with one refinement): for each article that had no rule, importing saves
a rule from **what was booked**, so a correction in the preview becomes the rule, not the AI's guess. Articles that
only got the fallback get no rule (my call), so the AI tries them again next time.

**Settings**: a list of article rules (name, category, tags) with a search field, edit and delete; parents only, like
the import rules.

## Meeting the payment

The family pays at Migros by TWINT or debit card (bank account), rarely credit card, almost never cash.

For each receipt the preview looks for its payment with the existing matching for receipts
(`reconcile.payments_for_receipt`): an expense with a bank row and no items, on a bank account the importer may
book on (own, or shared with edit rights, so the other parent's when shared), amount within CHF 1.00, paid from
3 days before to 30 days after the receipt. Exact amount first, then the nearest date.

- **Found**: the receipt goes onto that booking, as the receipt form's "add to this booking" does today: its lines
  and the receipt's date and description; the bank row stays. Several found → the first is chosen, the others can
  be picked in the preview.
- **Not found** (statement not imported yet, credit card, cash, the other parent's unshared account): the receipt
  is booked on an account chosen in the preview (default: the account of the latest receipt matched in this file,
  else the importer's first bank account; my call). A later bank import finds it as it finds Galaxus receipts today.
  Or the receipt is **left out** (unticked), e.g. for the other parent to import.

## Never twice

- Each receipt remembers its Migros key `migros:<Datum>:<Zeit>:<Filiale>:<Kassennummer>:<Transaktionsnummer>` (in
  `transactions.reference`, my call). A receipt whose key exists is shown as "already imported" and can't be
  ticked. Uploading overlapping months or both parents uploading is safe.
- A receipt that may already be booked another way (a booking with lines, on the same day, total within CHF 1.00,
  description or shop containing "Migros") is shown as "possibly already booked" and unticked by default.

## The preview

- One row per receipt: date and time, store, number of articles, total, the payment found ("TWINT Migros,
  12.09., CHF 247.86") or the account chosen, and the state (new / already imported / possibly already booked).
- A row opens to its articles: name, amount, category (changeable), tags (changeable), and where the category came
  from (rule / AI / fallback).
- Above: what the AI did (off / used / failed / limit) and how many new rules the import will save.
- Import books the ticked receipts; the result says how many were put onto payments, booked new, and rules saved.
- German and English; usable at phone width (the existing import is).

## Data

- New tables `article_rules` (id, name stored as typed, unique ignoring case, category_id, created_at) and
  `article_rule_tags` (rule_id, tag_id; both deleted with their row); migration 0020, additive.
- Deleting a tag removes it from article rules; Settings' tag usage counts article rules too. A category in use by a
  rule can't be deleted, or the rule goes with it, as for the import rules (builder: follow the import rules).
- Export: `article_rules.csv` in the analysis ZIP (name, category, tags).

## Left to the builder

- Where the Migros parsing lives (backend module) and how the preview/import API is shaped next to the bank import's.
- The AI prompt for categories and tags, and the fake AI's answer for tests.
- Exact wording, layout and icons, within the app's look.
