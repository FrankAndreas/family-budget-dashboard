# Import format for transactions

Family Budget can book many transactions at once from a file, for example one written by a tool that reads
receipts. Upload it in **Settings → Data Management → Import transactions**; a bank account's own CSV export works
too (see [Bank statements](#bank-statements)). The app checks every row and
shows a preview first; nothing is booked until you confirm, and then all rows are booked together or none.

The file is **CSV or JSON**, UTF-8, at most 1 MB and 1000 transactions.

## Fields

| Field | Required | Meaning |
|---|---|---|
| `date` | yes | `2026-10-12`, or ISO 8601 with time and offset (`2026-10-12T08:30:00+02:00`). A date alone is booked at 12:00 UTC so it stays on that day. Without an offset the time is UTC. |
| `account` | yes | Name of an account you can book on: your own, or one shared with you as "view and manage" |
| `owner` | no | Name of the account's owner. Only needed when two of those accounts have the same name; without it your own account is used |
| `category` | yes | Category name, e.g. `Groceries`. It decides whether the row is income or an expense. `Transfer` moves money between your own accounts (see below). "Settle up" can't be imported |
| `amount` | yes | Positive number with `.` as decimal point, e.g. `84.30` |
| `direction` | for `Transfer` | `out` (money leaves this account) or `in` (money arrives). Only for the category `Transfer` |
| `description` | no | e.g. the shop; at most 200 characters |
| `for` | no | Name of a child without own allowance the expense was for (parents' accounts only) |
| `shared` | no | Name of a split, e.g. `Equal 50/50`, if the parents share the cost (expenses on a parent's account only) |
| `item` | no | Name of the investment the expense belongs to (purchase, repair, service) |
| `reference` | no | Your tool's ID for the source, e.g. the receipt's file name or a hash; at most 200 characters |

Names are matched ignoring upper/lower case and surrounding spaces. A name that doesn't exist is an error:
the import never creates accounts, categories or anything else.

## CSV

A header row with the field names (any order, any case; unknown columns are ignored), then one row per
transaction. Separator `,` or `;` (taken from the header line). Quote fields containing the separator.

```csv
date,account,category,amount,description,for,shared,item,reference
2026-10-12,Postfinance,Groceries,84.30,Migros,,Equal 50/50,,receipt-0001.jpg
2026-10-13,Postfinance,Healthcare,120.00,Dentist,Timmy,,,receipt-0002.jpg
```

## JSON

```json
{
  "transactions": [
    {"date": "2026-10-12", "account": "Postfinance", "category": "Groceries", "amount": 84.30,
     "description": "Migros", "shared": "Equal 50/50", "reference": "receipt-0001.jpg"}
  ]
}
```

Leave out fields you don't use. In the app, **JSON Schema (for AI tools)** downloads a JSON Schema of this
format that lists the account, category, child, split and investment names valid for you. Tools that
support structured output (for example Ollama's `format` or llama.cpp's `--json-schema`) can use it so the
model can only produce a valid file. Download it again after adding accounts, splits or investments.

## Transfers between your own accounts

Money moved from one of the family's accounts to another (to the savings account, the joint account, a
credit card or a clearing account such as "Migros") is booked with the category **Transfer** on both
accounts: `out` on the account the money left, `in` on the one it arrived at. Each side usually comes from
that account's own export. Transfers count as neither spending nor income, so the purchases made with the
money aren't counted twice.

```csv
date,account,category,amount,direction,description,reference
2026-09-01,Household,Transfer,84.30,out,Migros,bank:3f2a91c07d5e8b14
2026-09-01,Migros,Transfer,84.30,in,From the household account,
```

A transfer can't be for a child, shared or linked to an investment. In the app, an imported transfer can be
deleted (and its date and description changed through the API), but not edited into something else.

## Converters

`tools/converters/` contains converters for a bank account's CSV export and for the Migros receipt export;
they write this format. See [their guide](../tools/converters/README.md).

## Changing categories in the preview, import rules

- In the preview, each income or expense row has a category dropdown. The sign stays: an expense row can become
  another expense category or **Transfer (out)**, an income row another income category or **Transfer (in)**.
  Each change checks the file again, so duplicates and errors match what will be booked.
- Parents can tick **remember** on a changed row and shorten the text (e.g. "Bäckerei"). The import then saves an
  **import rule**: bookings whose description contains that text as whole words, ignoring case, get that category.
  Rules are only saved when the import succeeds.
- Rules apply to rows that arrive as **Unsorted** or **Other Income** (the fallbacks of bank statements and the bank
  converter), when the category fits the sign. When several rules match, the longest text wins ("Migros Bank" before
  "Migros"). Such rows show "by rule: <text>". A change in the dropdown wins.
- **Settings → Data Management → Import rules** lists them: add, change and delete rules, tick **receipt expected**
  (see below) and copy the block to paste into `converter.toml`. **Add suggested rules** adds common Swiss shops and
  services; it is done automatically on a new database. The JSON Schema lists the rules as `x-rules`, and the bank
  converter applies them to lines its own rules don't recognise (see the [converters](../tools/converters/README.md)).

## Bank statements

Parents can upload a bank account's CSV export directly, without the converter. The app recognises it by its header
(Raiffeisen: `IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date`, UTF-8 or Windows-1252).

- **Account:** each line goes to the account whose **IBAN** matches (set it on the account in Settings; parents only). A line whose IBAN
  isn't on any account you can manage is an error.
- **Rows:** a card payment gets the purchase date and the merchant as its description; card numbers and IBANs are
  removed from the text. Lines with amount 0 are skipped (the preview counts them). Each line gets the same
  `reference` as the converter would give it (`bank:` and a hash), so importing a statement twice, or a converted
  file and the raw one, finds the duplicates.
- **Categories:** lines start as Unsorted / Other Income; rules replace that, then the receipt AI suggests categories
  for what is left, once, on the first preview (marked "AI"). Every suggestion can be changed in the dropdown.
- **Balance check:** the preview compares the statement's newest balance with the account's balance in the app
  after the import, counting only bookings the bank has confirmed.
- **Confirming bookings:** a line that pays a booking already in the app (a receipt typed in or read before the
  statement) confirms it instead of booking it again. The booking may be up to 30 days before the line or 3 days
  after it, and differ by up to CHF 1.00; an exact amount is preferred, then the nearest date. The preview shows the
  booking it picked; choose another one or **new booking**. A small difference is booked as a "Difference" item.
- **Receipt expected:** a rule with **receipt expected** marks its bookings, so the account shows "receipt missing"
  until a receipt is attached. A receipt that arrives after the statement can be put onto the bank booking that paid
  it from the receipt form.

After an account's first statement, its bookings show whether the bank confirmed them ("not confirmed", "no payment
found" once the newest statement is a week past the booking, "partly paid"), and the account card counts the
**open points**.

## Duplicates

A row is marked as a duplicate, and skipped unless you tick it in the preview, when
- its `reference` was already imported (or appears earlier in the same file), or
- it has no `reference` and a transaction on the same account has the same day, amount and category.

Giving every row a `reference` makes it safe to run the tool over the same receipts again.

## Errors

The preview lists every problem with its line (CSV: line in the file, header = line 1; JSON: position in
the list, starting at 1). A file with errors can't be imported; fix it and upload it again.

API: `POST /api/v1/import/preview` and `POST /api/v1/import` (multipart field `file`; `include_duplicates`:
comma-separated line numbers; `changes` and `matches`: JSON by line number; `ai=1`
on the preview of a bank statement), `GET /api/v1/import/schema`, `GET /api/v1/import/template.csv`.
