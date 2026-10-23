# Bank statements in the app, and receipts matched to bank rows

Date: 2026-10-23. Two parts, built and merged in this order:

1. **Bank CSV upload in the app**: accounts get an IBAN, the Raiffeisen CSV is uploaded directly in the import,
   rules are managed in Settings (with presets), and the AI suggests categories for rows no rule recognises.
2. **Receipts matched to bank rows (reconciliation)**: a receipt and the bank row that paid it are one booking.
   The receipt gives the items, the bank row confirms the money moved. Clearing accounts (Migros, Galaxus) are no
   longer needed for this.

## Why

Today a bank statement goes through `tools/converters/bank.py` on a computer: it maps IBANs to accounts through a
local `converter.toml` and writes an import file. An account in the app has no identifier, so a raw bank CSV can't
be imported in the app itself. The user wants to download the CSV from Raiffeisen and upload it in the app.

Shops whose receipts are booked item by item (Migros, Galaxus via the forwarded order confirmation) are paid with
TWINT from the bank account. Today that needs a clearing account per shop and a transfer rule, so the shop's
spending isn't counted twice. The user wants fewer accounts: the TWINT row on the bank account *is* the payment,
and the receipt with its items and tags hangs under it, opened and closed in the list.

## Goals

- Upload `IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date` (Raiffeisen) in the import; every row goes
  to the account carrying its IBAN, with a preview before anything is booked.
- Categories come from rules first, then the AI, then the fallback (Unsorted / Other Income).
- Rules are listed, added, edited and deleted in Settings; a new family starts with useful Swiss presets.
- A receipt and its bank payment are one booking with three visible states; open points are easy to find.

## Non-goals

- Credit card statements (no card export exists yet). The monthly card bill on the bank account is a normal row.
- Other banks' CSV formats. The parser is written so a second format can be added, but only Raiffeisen is built.
- Regex rules, "ignore" rules and the converter's `to_account` in the app. The converter stays as it is for anyone
  who still uses it; its README points to the direct upload.
- Converting existing data. The user's current data is not relevant; the NAS database may be wiped once when
  part 2 is deployed. **After that, migrations must keep data**: this is the last wipe.
- Tags from the AI for bank rows: the AI suggests categories only.

## Anti-goals

- No amounts, dates, IBANs, card numbers or balances sent to the AI: only the cleaned booking text.
- No warnings for rows where no receipt is expected: a warning that is always there gets ignored.
- No booking without the preview: the AI's answer is a suggestion, never booked unseen.
- No real IBANs, bank rows or receipts in the repo (public): tests use invented data (e.g. `CH93 0076 2011 6238
  5295 7`, the IBAN already in `converter.example.toml`).

---

## Part 1: bank CSV upload

### IBAN on accounts

- `accounts.iban`: optional, stored compact and uppercase (`CH9300762011623852957`), unique among accounts.
- Checked on save: two letters, two digits, 11–30 letters/digits, and the ISO 13616 mod-97 checksum. Error
  "That is not a valid IBAN" / "Das ist keine gültige IBAN"; a second account with the same IBAN: "Another account
  already has this IBAN".
- Entered and changed by parents in the account form (create and edit), shown grouped in fours
  (`CH93 0076 2011 6238 5295 7`). Children never see the field.
- Included in the data export; the export README mentions it.

### Recognising and reading the file

- The existing import (`POST /import/preview`, `POST /import`) accepts the bank file as well. A CSV whose header
  (ignoring case and spaces around names) contains `IBAN`, `Booked At`, `Text` and `Credit/Debit Amount`, separated
  by `;`, is a bank file; anything else is read as today. Encoding: UTF-8 with or without BOM, falling back to
  Windows-1252 (Raiffeisen exports with umlauts).
- Uploading a bank file is for parents only (403 "Only parents can import bank statements"), as rules are.
- Each line becomes a normal import row:
  - **account**: the account whose IBAN is the line's IBAN (compared compact, uppercase). None → the line is an
    error "No account has the IBAN CH93 … (add it to the account in Settings)". The IBAN is shown in the error to
    the parent; it is not logged.
  - **date**: for card lines (`Einkauf <merchant> 06.09.2026, 08:45, … -Nr. …`) the purchase date and time from
    the text, otherwise `Booked At` (Europe/Zurich, like the converter).
  - **amount and sign**: from `Credit/Debit Amount`; negative is money out. Amount 0 → skipped, listed as such.
  - **description**: the cleaned text: card lines become `<merchant>`, other lines lose card numbers and IBANs
    (the converter's `clean()`; move it into the backend, e.g. `backend/app/bank_csv.py`, and let the converter
    import nothing new — it keeps its own copy).
  - **reference**: `bank:` + the first 16 hex of sha256 of `iban|booked at|text|amount|balance`, exactly as the
    converter builds it, so a file converted before and the same file uploaded now are recognised as duplicates.
  - Overlapping uploads are skipped as duplicates by the existing reference check.
- Several IBANs in one file are fine: each line goes to its own account.
- **Balance check**: for every account in the file the preview shows the `Balance` of its latest line next to the
  app's balance for that account after this import. A difference is shown, not an error.

### Categories for bank rows

In this order; the first that gives one wins:

1. **Rules** (see below). The rule decides the category, or Transfer (then the row's sign is the direction).
2. **The AI**, only for rows still open and only when the receipt AI is set up (`receipt_ai.Settings.enabled`).
3. **Fallback**: Unsorted for money out, Other Income for money in.

The preview shows where each row's category came from: rule (with its text), AI, or fallback. Changing a row's
category and ticking "remember" saves a rule, as today.

#### The AI step

- The AI runs once per upload, not on every preview refresh: the first preview call of a bank file asks the AI;
  the frontend keeps the suggestions and sends them back as normal `changes` (category per line) on later preview
  calls and on the import, marked as coming from the AI so the preview can keep showing "AI".
- One call for the whole file: the distinct cleaned texts of the open rows (at most 200; more are left to the
  fallback, and the preview says so), with the family's expense category names for money-out texts and income
  names for money-in texts, in the person's language, like `receipt_ai.prompt`. Answer: JSON `{text: category}`;
  unknown names or a broken answer → those rows stay on the fallback, and the preview says the AI couldn't help.
- Counts as **one** read for the hourly AI limit (`take_read`); over the limit → fallback, with the limit message.
- The AI never suggests Transfer or Settle up; it only knows expense and income categories.
- Off, failing or slow (same timeout as receipts) → the preview works without it.

### Rules

`import_rules` gets:

- `text`: as today; matched **as whole words**, ignoring case: `CSS` matches "LSV CSS Versicherung" but not
  "ACCSSO". Matching works on the cleaned description. Special characters in the text (`&`, `.`, `'`) are literal.
- `category_id`: the category, or the Transfer system category.
- `receipt_expected` (bool, default false): rows booked by this rule expect a receipt (part 2). Shown and edited
  in part 1 already; used from part 2.
- **The longest matching text wins**; equal length → the older rule. So `DOSENBACH SPORT` beats `DOSENBACH`.

Settings → Data Management → Import rules (`ImportRules.tsx`) becomes a manager like tags:

- list (text, category, receipt expected), add, edit, delete; parents only; the TOML copy button stays.
- the form checks: text 2–120 characters, unique (ignoring case), a category of fitting type.
- the button **"Add suggested rules"**: adds the presets whose text isn't a rule yet, and the two new categories
  if they don't exist; tells how many were added.

#### Presets

A new database gets them with the default categories (`seed_categories` when it creates the defaults). Existing
families use the button. All presets have `receipt_expected = false`; the user adds Migros/Galaxus rules with the
flag (part 2).

Two new default categories (EXPENSE, with `default_key`, both languages, in `i18n.DEFAULT_NAMES`):

| key | en | de |
|---|---|---|
| `SPORT` | Sport | Sport |
| `COMMUNICATION` | Communication | Kommunikation |

| Text | Category |
|---|---|
| COOP, DENNER, ALDI, LIDL, MIGROS, VOLG | Groceries |
| SBB, TAMOIL, AVIA, SOCAR, MIGROL, GARAGE BUCHER, GARAGE WINDLIN | Transportation |
| SWISSCOM, SUNRISE, SALT, WINGO, YALLO, SERAFE | Communication |
| HELSANA, CSS, SWICA, SANITAS, CONCORDIA, APOTHEKE | Healthcare |
| ESPRIT, WE FASHION, JACK & JONES, CELINE, H&M, C&A, ZALANDO, S.OLIVER, TOM TAILOR, MARC O'POLO, STREET ONE, CECIL, CHICOREE, BONITA, MODEVA, NEW YORKER, ANOUK, CALIDA, BLACKOUT, BELLA DONNA, ULLA POPKEN, WORLD OF JEANS, DOSENBACH, OCHSNER SHOES | Clothing |
| OCHSNER SPORT, DECATHLON, DOSENBACH SPORT, WERUN, INTERSPORT, SPORT XX, BIKE-IMPORT, PROPAIN, ROSE BIKES, VELO LUSSI | Sport |

Plus `GARAGE WINDLING` (Transportation): the user wrote "Windling", the usual spelling is "Windlin", and whole-word
matching needs the exact word, so both are presets. "Word" means letters and digits; `-`, `.`, `&`, `'` and spaces
separate words, so `BIKE-IMPORT` matches "bike-import.ch" and `H&M` matches "H&M Stans".

### What part 1 changes elsewhere

- The JSON Schema `x-rules` for the converter keeps working (text, category, kind); it ignores the new fields.
- The import help text and `tools/converters/README.md` describe the direct upload.
- The receipt AI module gets a second prompt/parse pair for texts; the client and limit are shared.

---

## Part 2: receipts matched to bank rows

### The idea

One booking per payment. A booking can carry:

- **items** (from a receipt): what was bought, with categories, tags and persons — exists today;
- **attachments** (the receipt files) — exists today;
- **bank rows** (new): the line(s) of a bank statement that paid it.

A Migros TWINT payment is then one booking on the bank account. Its amount is what left the account; its items say
what it was. Budget and reports count the items (as they already do for receipts), never the booking twice.

### Data

New table `bank_rows`: `id`, `account_id`, `transaction_id` (nullable, ON DELETE SET NULL), `booked_on` (date),
`valuta_on` (date, nullable), `text` (cleaned), `amount` (Money, signed), `balance` (Money, nullable),
`reference` (unique), `imported_at`. A bank import (part 1's rows) writes one bank row per booked line, linked to the
booking it created or confirmed. Rows of part 1 imported before part 2 exist only as bookings with a reference; since
the database is wiped once at the part 2 deploy, no back-fill is needed.

`transactions.receipt_expected` (bool): set from the rule that booked the bank row; editable on the booking.

### States

Derived on read, never stored:

| State | Condition | Shown as |
|---|---|---|
| confirmed | sum of its bank rows = its amount | ✓, no badge |
| partly paid | bank rows exist, sum ≠ amount | "partly paid: CHF x of y" |
| not confirmed | no bank row, account is BANK or SAVINGS | "not confirmed" (neutral) |
| no payment found | not confirmed **and** a bank import of this account covers a date ≥ the booking's date + 7 days | warning "no payment found" |
| receipt missing | `receipt_expected` and no attachment | warning "receipt missing" |

- "Covers" = the account's latest `booked_on` among its bank rows. So a Galaxus receipt booked on 3 October shows
  only "not confirmed" until the October statement (imported early November) is in; then, if nothing matched, it
  warns.
- Bookings on CASH (and CLEARING) accounts have no confirmation state: cash is paid in cash.
- A booking with neither items nor `receipt_expected` and a bank row is just a confirmed plain booking.

### Matching

**Bank first, receipt later** (usual for receipts that come late): booking a receipt (ReceiptForm, also after an
inbox release) on a bank account looks for a booking on that account with a bank row, no items, and the same amount
(or within CHF 1.00), dated from the receipt date −3 to +30 days. Found → the form offers "add to this booking
(TWINT Migros, 03.10., CHF 84.30)"; chosen → the receipt's items and attachment go onto that booking, its date
becomes the receipt's date, its category becomes the items'. Several found → the person chooses; none or declined →
a new booking (not confirmed).

**Receipt first, bank later** (usual for Galaxus): the bank import preview, for each bank line, looks for
not-confirmed bookings on the line's account with the same amount (exact first, then within CHF 1.00), dated from
the bank date −30 to +3 days. One found → the line is shown as "confirms: Galaxus order, 03.10." and importing links
it instead of creating a booking. Several → the parent chooses in the preview. The parent can always switch a line
to "new booking".

**By hand**: on a booking, "link bank row" lists unlinked bank rows of the account (and those linked elsewhere, which
moves them), "unlink" detaches one. A bank row whose booking is deleted becomes unlinked and shows in a list
"bank rows without booking" on the account, from where it can be booked or linked.

**Several rows, several receipts**: a booking may have several bank rows (an order charged per parcel) and several
attachments (two receipts paid together). Part payments don't match by amount, so they are linked by hand; the
booking shows "partly paid" until the rows add up. A refund is its own bank row and its own booking (category by
rule/AI).

**Settling up and other in-app bookings**: a settle-up transfer or any booking typed in by hand on a bank account is
"not confirmed" like a receipt, and the bank line that paid it matches it the same way, so it isn't booked twice.

### Differences

When a receipt's total and the bank amount differ (Cumulus, deposit, tip, voucher, rounding):

- The booking's amount is the bank amount (what left the account).
- The difference becomes an item "Difference" / "Differenz" with the category of the receipt's largest item,
  editable like any item.
- Above CHF 1.00 the booking shows a warning "receipt and payment differ by CHF x" until the parent marks it as
  accepted (a flag on the booking, `difference_accepted`).

### Dates

The budget month is the purchase date: the booking's `date` is the receipt's date (or the card purchase date from
the text). Bank rows keep their own `booked_on`/`valuta_on`. The month check and account balance by month use
`date` as today.

### Balances

An account's balance stays the sum of its bookings (unchanged). The account card additionally shows "of which not
confirmed: CHF x", so the balance can be compared with the bank's by subtracting it. The part 1 balance check in the
import preview compares the bank's balance with confirmed bookings only.

### In the list

- Transactions show a state badge (above). A booking with items or attachments expands (▸) to its items (with tags
  and persons), its receipts (open the file) and its bank rows (date, text, amount); collapsed by default.
- A filter "open points": not confirmed, no payment found, receipt missing, partly paid, differs.
- The account card and the month check show the number of open points with a link to that filter.

### Rules in part 2

A rule's `receipt_expected` is used: the bank row's booking gets the flag. The user then creates e.g.
`TWINT MIGROS → Groceries, receipt expected` and `GALAXUS → Unsorted, receipt expected`. When the receipt is added,
its items replace the category.

### Clearing accounts

Stay as they are (type, month check); nothing new uses them. No preset or help text recommends them any more.

## Left to the builder

- Endpoint and component names beyond those named here, and how the preview carries the AI marks and the chosen
  matches (form fields like today's `changes`).
- Splitting part 1 and part 2 each into reviewable PRs.
- The exact German and English texts, following the existing tone in `de.ts` / `en.ts` and `messages.py`.
