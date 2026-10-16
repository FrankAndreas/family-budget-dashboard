# Import preview: change categories, remember them as rules

Date: 2026-10-16. Status: draft, for review. Issue #16.

## Goal

A booking the bank converter doesn't recognise arrives as "Unsorted" (or the income fallback) and today has to be
re-categorised after the import, one by one. Instead:

1. **Change the category in the import preview**, before anything is booked.
2. **Remember it as a rule** in the app, so the next import recognises it.
3. **Export the rules to the converter**, so one rule serves both the app and `bank.py` without editing files.

Decided with the user: the rules live in the app (not only in `converter.toml`); they reach the converter through
the JSON Schema download it already uses, and each rule can also be copied as a TOML block for `converter.toml`.

## 1. Category dropdown in the preview

- Every row without errors gets a category dropdown in the preview, except rows that are a Transfer in the file,
  and Settle up is never offered.
- **The sign stays.** The file's category decides whether the row is money out or in:
  - a row whose file category is an **expense** may become another expense category or **Transfer (out)**;
  - a row whose file category is **income** may become another income category or **Transfer (in)**.
  A change to Transfer sets `direction` (out / in) for that row.
- Changing a category runs the preview again with all changes so far, so duplicates and errors are always computed
  exactly as the import will book them. The import sends the same changes.
- A changed row shows the file's category struck through next to the dropdown.

### API

`POST /import/preview` and `POST /import` take a new optional form field **`changes`**: JSON
`{"<line>": {"category": "<name>", "remember": "<text or empty>"}}`.

- Applied to the raw row before it's checked. A change on a line that doesn't exist, on a Transfer row, to an
  unknown category, to Settle up, or across the sign (expense ↔ income) makes that row an error:
  "Can't change <file category> to <new category>".
- `remember` is checked by both (section 2), but only `POST /import` saves rules.
- Each preview row gets two new fields: `file_category` (the category as in the file) and `rule` (the text of the
  app rule that set the category, or null).
- Invalid `changes` JSON → 400 "changes must be JSON".

## 2. Import rules in the app

### Data

New table `import_rules`:

| Column | Notes |
|---|---|
| `id` | uuid |
| `text` | 2–120 characters, stored as typed (trimmed); matched ignoring case |
| `category_id` | an INCOME, EXPENSE or TRANSFER category (not Settle up) |
| `created_at` | |

Text is unique ignoring case: remembering the same text again updates its category.

### Remembering

- In the preview, a changed row of a **parent** shows "☐ remember" with a text field filled with the row's
  description (editable, e.g. shortened to "Bäckerei"). Children don't see it.
- On `POST /import`, each change with a non-empty `remember` creates or updates a rule: that text → the row's new
  category. Rules are only saved when the import succeeds (same transaction). Text shorter than 2 or longer than
  120 characters makes that row an error ("rule text: 2 to 120 characters").
- A `remember` from a child → 403 "Only parents can save import rules".

### Applying

- In preview and import, rows whose file category is **Unsorted** (expense) or **Other Income** (income) and that
  have no change from the user are checked against the rules, oldest first. The first rule whose text is contained
  in the row's description (ignoring case) and whose category fits the row's sign (expense rule → expense row,
  income rule → income row, Transfer rule → either, with direction out for an expense row and in for an income row)
  sets the category; `rule` names it.
- A change in the dropdown wins over a rule.
- Rules are family-wide: every import uses all of them.

### Settings → Import rules

A section under Data Management, for parents: the rules (text → category), oldest first, with **Delete** and
**Copy for converter.toml** (copies the rule's TOML block to the clipboard; the block is also shown on hover).

API: `GET /import/rules` (parents) → `[{id, text, category, category_type, toml}]`;
`DELETE /import/rules/{id}` (parents).

The TOML block (built on the server, so the escaping is tested):

```toml
[[bank.rules]]
match = "Bäckerei"          # the text as a regular expression (re.escape), as a TOML basic string
category = "Groceries"      # or, for a Transfer rule: action = "transfer"
```

## 3. Rules in the converter

- `GET /import/schema` gets `"x-rules": [{"contains": "<text>", "category": "<name>"}, ...]` (oldest first).
- `bank.py` applies them to lines **none of its own rules** recognise, before the fallback, with the same matching
  as the app (contained in the cleaned description, ignoring case, sign must fit; Transfer → `direction` from the
  sign, no `to_account`).
- The report counts them separately: "N by app rule", and they are not listed as unrecognised.
- A rule in `converter.toml` always wins, because it is checked first.
- The Migros converter doesn't use them.

## Error handling

- Section 1 and 2 errors appear as row errors in the preview, like all other import errors; nothing is imported
  while any row has an error.
- Deleting a category that rules use isn't possible today (no category management, #22); when #22 comes, it has
  to handle rules.

## Testing

- **Backend (pytest, `tests/test_import_rules.py`):** change expense → expense, expense → Transfer (out), income →
  Transfer (in); across the sign, to Settle up, to an unknown category, on a Transfer row → row error; changes
  affect duplicate detection; import with `remember` creates a rule, same text updates it, child → 403, rule text
  length; rules applied to Unsorted / Other Income rows only, oldest first, sign must fit, dropdown change wins,
  `rule` and `file_category` fields; a failed import saves no rule; `GET`/`DELETE /import/rules` parents only;
  TOML block escaping (quotes, backslash, regex characters like `.` and `(`); schema `x-rules`.
- **Converter (`tests/test_converters.py`):** app rules from `x-rules` apply only to lines no own rule matches,
  sign must fit, Transfer direction, report count, own rule wins.
- **Frontend:** lint, type-check, build; browser test: import a file with an Unsorted row, change it to Groceries
  with "remember" shortened text, import; import a second file with a matching row: it arrives as Groceries
  "by rule"; Settings shows the rule and its TOML block.

## Out of scope

- Rules with `for`, `shared` or `item`; regular expressions in app rules; editing a rule (delete and remember again).
- Applying rules to transactions already booked.
- Rules for the Migros converter.
