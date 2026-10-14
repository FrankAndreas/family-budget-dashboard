# Import format for transactions

Family Budget can book many transactions at once from a file, for example one written by a tool that reads
receipts. Upload it in **Settings → Data Management → Import transactions**: the app checks every row and
shows a preview first; nothing is booked until you confirm, and then all rows are booked together or none.

The file is **CSV or JSON**, UTF-8, at most 1 MB and 1000 transactions.

## Fields

| Field | Required | Meaning |
|---|---|---|
| `date` | yes | `2026-10-12`, or ISO 8601 with time and offset (`2026-10-12T08:30:00+02:00`). A date alone is booked at 12:00 UTC so it stays on that day. Without an offset the time is UTC. |
| `account` | yes | Name of an account you can book on: your own, or one shared with you as "view and manage" |
| `owner` | no | Name of the account's owner. Only needed when two of those accounts have the same name; without it your own account is used |
| `category` | yes | Category name, e.g. `Groceries`. It decides whether the row is income or an expense. "Settle up" can't be imported |
| `amount` | yes | Positive number with `.` as decimal point, e.g. `84.30` |
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

## Duplicates

A row is marked as a duplicate, and skipped unless you tick it in the preview, when
- its `reference` was already imported (or appears earlier in the same file), or
- it has no `reference` and a transaction on the same account has the same day, amount and category.

Giving every row a `reference` makes it safe to run the tool over the same receipts again.

## Errors

The preview lists every problem with its line (CSV: line in the file, header = line 1; JSON: position in
the list, starting at 1). A file with errors can't be imported; fix it and upload it again.

API: `POST /api/v1/import/preview` and `POST /api/v1/import` (multipart field `file`; `include_duplicates`:
comma-separated line numbers), `GET /api/v1/import/schema`, `GET /api/v1/import/template.csv`.
