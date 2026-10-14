# Bank and Migros converters, and transfers in the import

Date: 2026-10-14. Status: draft, for review.

## Goal

Most household spending is paid by debit card and TWINT, so the bank's CSV export already holds every
payment with an exact amount and date. OCR or an LLM isn't needed. Two small converters turn exports into
the app's existing import format (`docs/import-format.md`). The import shows the preview and books the rows.

1. **Bank converter:** the bank account's CSV export goes through a rules file and becomes import rows.
2. **Migros converter:** the Migros receipt export ("Kassenbeleg") becomes one expense per receipt and
   category on a "Migros" account.
3. **App change:** a general **Transfer** category that the import accepts. Money moved between the
   family's own accounts is then booked on both sides without counting as spending or income.

Decided with the user:
- One export file always belongs to one account, and one booking is one line.
- Each account keeps its own balance. A transfer between two accounts in the app is booked twice, once
  from each account's export. These are the two sides of one movement, not duplicates.
- The same purchase is booked from one source only. Spending at Migros comes from the receipts; the bank
  side of it is a Transfer to the Migros account. The same applies later to the credit card: the Viseca
  bill is a Transfer, and the card's own export books the purchases.
- Clearing accounts (Migros, credit card) won't always end at 0: lost receipts, purchases without the
  Cumulus card, or untracked gift cards and bonuses. For now the difference is booked by hand; a
  "Reconcile" helper is issue #21.
- Unrecognised lines get a fallback category and are corrected in the app after the import. A category
  dropdown in the preview is issue #16.
- TWINT credits ("money back from a person") are booked as income, "Reimbursements". The match with the
  original expense isn't exact and doesn't need to be.
- The Cembra standing order is a car leasing: an expense with the car from the inventory as `item`.
- No real IBANs, names or bookings in tests, docs or examples; the repository is public.

## 1. App: the Transfer category

- `seed.py` adds three categories: **Transfer** (`TRANSFER`), **Unsorted** (`EXPENSE`) and
  **Reimbursements** (`INCOME`). They are created on start-up like the others, also in existing databases.
- "Settle up" stays as it is: booked only by settling up in the Common tab, never imported, never edited.
- **Import:** rows with the category Transfer are accepted. They need a new field **`direction`**: `out`
  (money leaves this account, booked negative) or `in` (money arrives, booked positive). `direction` on a
  row with another category is an error, and so is a Transfer row without it. Transfer rows can't carry
  `for`, `shared` or `item`. Settle up is still rejected with the same message.
- **Schema** (`GET /import/schema`): `category` lists Transfer too; new property `direction`
  (`enum: ["in", "out"]`); new top-level `"x-category-types": {"<name>": "INCOME" | "EXPENSE" | "TRANSFER"}`
  so a tool can check that a credit doesn't land in an expense category.
- **Template and docs:** `docs/import-format.md` gets the `direction` field and a paragraph on transfers.
- **Transactions in the Transfer category** can be deleted (balance adjusted), and their date and
  description can be edited. Changing their category or amount isn't allowed (delete and re-import
  instead), and no other transaction can be changed into a Transfer. The edit and delete buttons in the
  dashboard stay hidden for Settle up only. The manual form doesn't offer Transfer (booking a transfer
  by hand is out of scope).
- Analytics, budgets and the export already leave out `TRANSFER` categories; nothing changes there.
- Duplicate check: unchanged. The two sides of one transfer are on different accounts, so they never
  match each other.

## 2. Converters: common parts

Location: `tools/converters/` in the repository, Python 3.11+ standard library only (`csv`, `tomllib`,
`zoneinfo`, `hashlib`, `json`, `re`). They run on a PC or on the NAS:

```
python3 tools/converters/bank.py   bank-export.csv   --config converter.toml --schema import-schema.json
python3 tools/converters/migros.py kassenbeleg.csv   --config converter.toml --schema import-schema.json
```

- **Output:** `<input name>-import.csv` next to the input, in the import format (`,` separator, UTF-8).
  Upload it in Settings → Data Management → Import transactions.
- **Report** on the console: number of rows booked, transferred and ignored; every unrecognised line;
  every rule problem; plus the converter's own check (bank balance, receipt totals per day; see below).
- **Input reading:** `;` or `,` separator, UTF-8 with or without BOM, falling back to Windows-1252.
  Header names compared case-insensitively. A missing required column stops the converter with a message.
- **Schema** (`--schema`, required): the JSON Schema downloaded from the app. The converter checks before
  converting that every account, category and item named in the config exists. It also checks that a
  rule's category type fits the booking's sign (credit → income, debit → expense, transfer → either).
  Problems are listed and the converter stops, so nothing half-right is written.
- **Dates:** local Swiss time. A date with a time is written as ISO 8601 with the `Europe/Zurich` offset.
  A date without a time is written as `YYYY-MM-DD` (the import books it at 12:00 UTC).
- **Amounts:** always positive in the output; the category (or `direction`) gives the sign.
- **References:** every row gets one, so running a converter twice over overlapping exports only produces
  duplicates in the preview (see each converter).
- **Config:** one TOML file, kept outside the repository (it contains IBANs and names).
  `tools/converters/converter.example.toml` is a documented example with made-up values. `converter.toml`
  is git-ignored.

## 3. Bank converter

Input columns (as exported by the bank): `IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date`.

### Config

```toml
[bank.accounts]                     # IBAN of the export → account in the app
"CH9300762011623852957" = { account = "Household", owner = "Alex" }   # owner optional

[bank.fallback]
expense = "Unsorted"                # debit line no rule matches
income  = "Other Income"            # credit line no rule matches

[[bank.rules]]                      # first match wins; match = regular expression, case-insensitive
match = "^Einkauf .*\\bMIGROS\\b"
action = "transfer"                 # money to the Migros clearing account
description = "Migros"

[[bank.rules]]
match = "^LSV Viseca"
action = "transfer"

[[bank.rules]]
match = "^Übertrag (von|auf) "
action = "transfer"

[[bank.rules]]
match = "^Dauerauftrag Cembra"
category = "Transportation"
item = "Family car"                 # investment from the inventory

[[bank.rules]]
match = "^Gutschrift TWINT "
category = "Reimbursements"

[[bank.rules]]
match = "^Gutschrift .*ACME AG"
category = "Salary"

[[bank.rules]]
match = "^Einkauf .*\\bBäckerei\\b"
category = "Groceries"

[[bank.rules]]
match = "^Bargeldbezug"
action = "ignore"
```

Rule fields: `match` (required), `action` = `book` (default), `transfer` or `ignore`, `category` (required
for `book`), optional `sign` = `debit` or `credit` (the rule applies only to that direction), `description`
(replaces the cleaned text), `item`, `for`, `shared`.

### Per line

1. The IBAN must be in `[bank.accounts]`, otherwise the converter stops (wrong file or config).
2. **Text cleaning** (used for matching and as description):
   - debit card: `Einkauf <merchant> dd.mm.yyyy, hh:mm, Debit Mastercard-Nr. …` → the merchant only, and
     the date and time in the text become the transaction's date;
   - card and account numbers (anything after `Mastercard-Nr.`, IBANs) are removed;
   - other lines: the text as it is, without repeated spaces. Rules match against the original text
     (after removing card numbers), so prefixes like `Einkauf TWINT` stay usable.
3. The first matching rule decides; `sign` restricts a rule to debits or credits. Without a match:
   fallback category by sign, and the line is listed as unrecognised.
4. Output row: `date`; `account` and `owner` from the config; `category`; `amount` = absolute value;
   `description` (at most 200 characters); `item`, `for`, `shared` from the rule; `direction` = `out`
   for a debit, `in` for a credit (Transfer only); `reference` = `bank:` + the first 16 hex characters of
   SHA-256 over `IBAN|Booked At|Text|Amount|Balance`. The balance makes two equal purchases on the same
   day distinct.
5. A line with amount 0 is skipped and reported.

### Balance check

The report states the bank's balance after the latest booking (the `Balance` of the line with the latest
`Booked At`; if several share that date, the first one in the file). After the import, the account's
balance in the app should match it, provided all earlier bookings are in the app too.

## 4. Migros converter

Input columns: `Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz`, one line
per article. `Umsatz` is taken as the amount paid for the line, with the discount (`Aktion`) already taken
off. This is an assumption: if it turns out wrong, the Migros account will show the difference.

### Config

```toml
[migros]
account = "Migros"                  # clearing account in the app
owner = "Alex"                      # optional
default_category = "Groceries"
refund_category = "Reimbursements"  # a receipt and category whose total is negative (returns, deposit)

[[migros.branches]]                 # by branch name, first match wins
match = "Do it|Garden"
category = "Other Expense"

[[migros.articles]]                 # by article name; wins over the branch
match = "Windeln|Pampers"
category = "Other Expense"
for = "Kim"
```

### Per receipt

1. A receipt is the group of lines with the same `Datum`, `Filiale`, `Kassennummer` and
   `Transaktionsnummer`.
2. Each line's category: the first matching article rule, else the first matching branch rule, else
   `default_category`. Article rules may also set `for`.
3. One output row per receipt, category and `for`: `date` = `Datum` + `Zeit` with the Zurich offset;
   `account`/`owner` from the config; `amount` = sum of `Umsatz` (rounded to cents);
   `description` = `Migros <Filiale>`; `reference` = `migros:<Datum>:<Filiale>:<Kassennummer>:<Transaktionsnummer>:<category>:<for>`.
   A sum of 0 is skipped; a negative sum is booked with `refund_category` as a positive amount.
4. Changing the rules and converting the same file again changes the references, so the preview won't
   recognise those receipts as already booked. The report warns about this in its summary line.

### Totals check

The report lists the receipt totals per day, so they can be compared with the Migros transfers from the
bank converter. The Migros account in the app should end near 0; the rest is reconciled by hand (#21).

## Error handling

- Config or schema problems (unknown account, category or item; rule without category; invalid regular
  expression; category type that can't fit the rule's sign): listed together, nothing written, exit code 1.
- Input problems (missing column, unreadable number or date): the line number and the reason are listed,
  nothing written, exit code 1. A partly converted file is never written.
- The app's import checks everything again; the converter's checks only catch mistakes earlier.

## Testing

- **App (pytest):** Transfer rows imported with `direction` in and out (balance changes, sign); missing or
  wrong `direction`; `direction` on a non-transfer row; Settle up still rejected; Transfer with
  `for`/`shared`/`item` rejected; schema lists Transfer, `direction` and `x-category-types`; a Transfer
  transaction can be deleted and its description edited but not its category or amount; Settle up can
  still be neither; the seed creates the three categories in an existing database.
- **Converters (pytest, `tests/test_converters.py`)** with invented exports in the test file:
  every text kind seen so far (card purchase with date in text, TWINT purchase, TWINT to a person, TWINT
  credit, salary credit, standing order, e-bill payment, LSV, transfer between own accounts); first match
  wins; `sign`; fallback and unrecognised list; card number removed; reference stable and distinct for two
  equal purchases; config checks against a schema; Windows-1252 input; balance check; Migros grouping by
  receipt, article over branch over default, `for`, negative and zero sums, totals per day.
- **End to end:** convert an invented bank export and Migros export, upload both through the import
  preview in a scratch backend, and check the balances: bank account as reported, Migros account at 0.
- Frontend: lint, type-check, build. The import preview shows `direction` like the other optional fields.

## Out of scope

- The Viseca card converter (needs a sample of its export first).
- A category dropdown and "remember as rule" in the import preview (#16), reconcile (#21).
- Booking a transfer by hand in the app, creating categories in the app (no UI for it yet).
- Matching Migros receipts to bank payments automatically.
- Running the converters on a schedule on the NAS.
