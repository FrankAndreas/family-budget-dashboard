# Receipts Matched to Bank Rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One booking per payment: a bank statement line confirms a booking, a receipt details it, and the list shows
what is confirmed, not confirmed, unpaid, missing its receipt, partly paid or different.

**Architecture:** A new `bank_rows` table keeps every imported statement line, linked to the booking it created or
confirmed. A new module `backend/app/reconcile.py` derives the states on read, fits a receipt's items to the bank
amount (difference item), finds matching candidates in both directions, and holds the link/unlink/book endpoints.
The part 1 bank import writes bank rows and links lines to existing bookings; the receipt form offers an existing bank
booking to put the receipt on.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite; React 19 + TypeScript + react-i18next; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-23-bank-import-and-reconciliation-design.md` (Part 2). Part 1 is merged
(PR #78): `bank_csv.py`, `import_api.check_file` → `(rows, is_bank)`, rows carry `_account`, `_booked`, `_balance`,
`source`, `rule`; `import_rules.find`; `models.ImportRule.receipt_expected`.

## Global Constraints

- No real IBANs, bank rows or receipts in the repo; test data invented (`CH93 0076 2011 6238 5295 7`, "Muster", "Beispiel").
- New migration `0013`, `database_setup.HEAD = "0013"`. It keeps data. (The user may wipe the NAS DB once at this
  deploy; after that, migrations must keep data.)
- Every new user-visible text in `messages.py` (en + de) or `frontend/src/locales/{en,de}.ts`; German Swiss
  spelling (ss), informal "du".
- Tolerance for amounts that "match" and for a difference that warns: **CHF 1.00**. Match windows: a booking dated
  from the bank line's date **−30 days to +3 days** (seen from the bank line), i.e. a bank line from the receipt's
  date **−3 to +30 days** (seen from the receipt). "No payment found" once the account's latest bank line is at least
  **7 days** after the booking's date.
- States exist only on BANK and SAVINGS accounts **that have at least one bank row** (plan call, see Rulings in
  the plan below); CASH and CLEARING never have states.
- Checks before the PR: `pytest tests -q -p no:warnings`; from `backend/`: `black --check app ../tools ../tests`,
  `flake8 app ../tools --max-line-length=120 --extend-ignore=E203,W503`, `mypy app/ ../tools/ --ignore-missing-imports`;
  `cd frontend && npm run lint && npm run type-check && npm run build`; `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npm test`.

## Plan calls (decided here, beyond the spec)

- **States only after the first bank import of an account.** Before any statement is imported, every booking would
  be "not confirmed" and the card would show the whole balance as unconfirmed — noise the spec's anti-goal forbids.
- **The month check stays as it is** (clearing accounts only). The open-point count is on the account card and as a
  filter in the list; bank accounts have no month check to put it on.
- **Several candidates in the import preview:** the best one (exact amount, then nearest date) is preselected and the
  parent can switch to another or to "new booking". A candidate is used by at most one line of a file.
- **The difference** is stored on the booking (`transactions.difference`, bank amount minus receipt total, set when
  items are fitted to the bank) and the item "Difference"/"Differenz" carries it. Editing the items again re-fits:
  the old difference item is then an ordinary item and the new difference is what's left (usually 0).
- **Bank rows without booking** are listed under the account's open points, with "book" (choose a category) and
  "link" (choose a booking).

## Review Focus

1. Re-uploading a statement after some lines were linked to receipt bookings must not book those lines again: the
   duplicate check must know bank rows' references — Task 1 (`test_linked_line_is_duplicate_on_reupload`).
2. Two lines with the same amount near the same receipt: only one may confirm it — Task 4
   (`test_candidate_used_once`).
3. Deleting a booking must not delete its bank rows, and deleting an account must not fail on them — Task 1
   (`test_delete_booking_keeps_row`, `test_delete_account_with_rows`).
4. A receipt put on a bank booking must keep the bank's amount (the balance must not change) — Task 3/5
   (`test_items_fitted_to_bank`, `test_receipt_onto_payment_keeps_balance`).
5. A booking on an account without any bank import shows no state and no warning — Task 2
   (`test_no_states_before_first_import`).

---

### Task 1: Bank rows

**Files:**
- Create: `backend/app/migrations/versions/0013_bank_rows.py`
- Modify: `backend/app/models.py` (BankRow; Transaction: `receipt_expected`, `difference`, `difference_accepted`,
  relationship `bank_rows`), `backend/app/database_setup.py` (`HEAD = "0013"`), `backend/app/import_api.py`
  (`run_import`, `Lookups.references`), `backend/app/crud.py` (`delete_account`)
- Test: `tests/test_bank_rows.py`

**Interfaces:**
- Produces: `models.BankRow` (`bank_rows`): `id` (uuid str), `account_id` (FK accounts, not null, index),
  `transaction_id` (FK transactions ON DELETE SET NULL, nullable, index), `booked_on` (Date), `valuta_on` (Date,
  nullable), `text` (String, the cleaned description), `amount` (Money, signed), `balance` (Money, nullable),
  `reference` (String, unique), `imported_at` (DateTime, default utcnow). `Transaction.bank_rows` (relationship,
  order by booked_on; `passive_deletes=True`, no cascade delete). `Transaction.receipt_expected: bool` (default
  False), `difference: Optional[float]` (Money), `difference_accepted: bool` (default False).
- `bank_csv.rows` adds `_valuta` (date or None). `run_import` for a bank file: per booked row, one BankRow with the
  row's account, `_booked`, `_valuta`, description, signed amount, `_balance`, reference, linked to the created
  booking. `Lookups.references` also maps each visible bank row's reference to its booking (or to a placeholder
  for an unlinked row, so it still counts as a duplicate). `crud.delete_account` deletes the account's bank rows
  before its transactions.

- [ ] **Step 1: Write the failing tests**

```python
def test_import_writes_bank_rows(client):  # bank file with 2 lines → 2 bank_rows, each linked to its booking; text, signed amount, booked_on, valuta_on, balance stored
def test_normal_import_writes_none(client):
def test_linked_line_is_duplicate_on_reupload(client):  # link a bank row to another booking (set transaction_id in the DB), delete the booking it created → re-upload: line is "duplicate"
def test_delete_booking_keeps_row(client):  # DELETE /transactions/{id} → bank row stays, transaction_id None
def test_delete_account_with_rows(client):  # DELETE /accounts/{id} → 200, no bank rows of it left
def test_migration_0013(tmp_path):  # upgrade from 0012 with a transaction: new columns default False/None, table exists
```

- [ ] **Step 2: Run** `pytest tests/test_bank_rows.py -q -p no:warnings` — Expected: FAIL (no table).
- [ ] **Step 3: Implement** model, migration (FKs as in the model; unique index on reference), import changes.
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: imported bank lines are kept as bank rows`

### Task 2: States and open points

**Files:**
- Create: `backend/app/reconcile.py`
- Modify: `backend/app/schemas.py` (Transaction, Account, TransactionUpdate), `backend/app/api.py` (accounts list,
  account transactions with `open`), `backend/app/import_api.py` (`receipt_expected` from the rule),
  `backend/app/crud.py` (`update_transaction` accepts the two flags)
- Test: `tests/test_reconcile_states.py`

**Interfaces:**
- Produces in `reconcile.py`:
  - `TOLERANCE = 1.00`, `NO_PAYMENT_DAYS = 7`.
  - `covered_until(db, account_id) -> Optional[date]` — latest `booked_on` of the account's bank rows.
  - `state(transaction, account, covered: Optional[date]) -> dict` → `{"confirmation": str | None,
    "receipt_missing": bool, "differs": bool}`; confirmation is `None` (CASH/CLEARING, or `covered` is None),
    `"confirmed"` (bank rows sum = amount), `"partly_paid"` (rows, sum ≠ amount), `"not_confirmed"`,
    `"no_payment"` (not confirmed and `covered >= booking's Swiss date + 7 days`). `receipt_missing` =
    `receipt_expected` and no attachment. `differs` = `abs(difference) > TOLERANCE` and not `difference_accepted`.
  - `is_open(state: dict) -> bool` — confirmation in (not_confirmed, no_payment, partly_paid) or receipt_missing or
    differs.
  - `annotate(db, transactions: list[models.Transaction]) -> list` — sets `t.state` on each (one coverage query per
    account).
  - `summary(db, account) -> dict` → `{"open_points": int, "not_confirmed": float}` (sum of amounts of bookings
    without bank rows, only when the account has states; else 0) plus `unlinked_rows` count included in open points.
- Schemas: `Transaction` gets `bank_rows: list[BankRowOut]` (id, booked_on, valuta_on, text, amount),
  `receipt_expected: bool = False`, `difference: Optional[float] = None`, `difference_accepted: bool = False`,
  `state: Optional[dict] = None`. `Account` gets `open_points: int = 0`, `not_confirmed: float = 0`.
  `TransactionUpdate` gets `receipt_expected: Optional[bool]`, `difference_accepted: Optional[bool]` (allowed on any
  booking, also ones with items or transfers).
- `GET /accounts/{id}/transactions?open=1` → only `is_open` bookings (all of them, no paging); without `open`
  as today but annotated. `GET /accounts` annotates each account with `summary`.
- Import: a bank row booked by a rule with `receipt_expected` creates its booking with `receipt_expected=True`.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_states_before_first_import(client):  # plain booking on BANK account, no bank rows anywhere → state confirmation None, open_points 0
def test_confirmed_by_import(client):  # imported bank line → its booking "confirmed"
def test_not_confirmed_then_no_payment(client):  # booking 2026-09-03 typed in; import a line dated 2026-09-09 → "not_confirmed"; import a line dated 2026-09-10 → "no_payment"
def test_partly_paid(client):  # booking −100 with one linked row −40 (DB) → "partly_paid"
def test_receipt_missing_from_rule(client):  # rule MUSTER receipt_expected → imported booking receipt_missing True; attachment added (POST /transactions/{id}/attachments) → False
def test_differs_and_accept(client):  # difference −2.50 set in DB → differs True; PUT difference_accepted → False
def test_cash_has_no_state(client):
def test_open_filter_and_summary(client):  # GET ?open=1 lists only open ones; GET /accounts open_points and not_confirmed (sum of unconfirmed amounts)
def test_toggle_receipt_expected(client):  # PUT {receipt_expected: true} on a plain and on a receipt booking → 200
```

- [ ] **Step 2: Run** `pytest tests/test_reconcile_states.py -q -p no:warnings` — Expected: FAIL (no `state`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: bookings show whether the bank confirmed them`

### Task 3: Fitting items to the bank, linking by hand

**Files:**
- Modify: `backend/app/reconcile.py`, `backend/app/api.py` (`create_receipt`, `update_receipt` call `fit`),
  `backend/app/main.py` (router), `backend/app/messages.py`
- Test: `tests/test_bank_links.py`

**Interfaces:**
- Produces:
  - `reconcile.fit(db, transaction) -> None` — when the booking has items and bank rows: target = sum of bank rows;
    if `items total ≠ |target|`, append an item named `messages.text("difference_item")` ("Difference" /
    "Differenz") with the booking's main category (`transaction.category_id`) and amount `|target| − items total`
    (may be negative), set `transaction.amount = target`, `transaction.difference` = that amount; else
    `difference = None`. A plain booking with bank rows: `amount` = target when within `TOLERANCE`, else unchanged.
    The caller commits.
  - `POST /transactions/{id}/bank-rows/{row_id}` — link (moves it from another booking); write access to the
    booking's account; the row's account must be the booking's (400 `bank_row_other_account` "That bank line belongs
    to another account" / "Diese Bankzeile gehört zu einem anderen Konto"); then `fit`. Returns the annotated booking.
  - `DELETE /transactions/{id}/bank-rows/{row_id}` — unlink (row stays, `transaction_id` None).
  - `GET /accounts/{id}/bank-rows?unlinked=1` — bank rows of the account (read access), newest first; `unlinked=1`
    only those without booking.
  - `POST /bank-rows/{row_id}/book` body `{"category_id": str}` — a plain booking from an unlinked row (date =
    booked_on, amount and sign from the row, description = text; Transfer gets direction from the sign; Settle up
    refused like the import), linked to it. 400 `bank_row_linked` "This bank line already has a booking" / "Diese
    Bankzeile hat schon eine Buchung" when linked.

- [ ] **Step 1: Write the failing tests**

```python
def test_items_fitted_to_bank(client):  # imported line −84.30; PUT items summing 83.40 → amount −84.30, difference item 0.90 "Difference", difference 0.90, balance unchanged
def test_items_equal_to_bank_no_difference(client):
def test_negative_difference(client):  # items 86.00 for −84.30 → difference item −1.70, differs True
def test_link_and_unlink(client):  # booking typed in, unlinked row (row's own booking deleted) → link → confirmed; unlink → not_confirmed
def test_link_moves_row(client):
def test_link_other_account_refused(client):
def test_link_needs_write_access(client):  # VIEW share → 403
def test_list_unlinked_rows(client):
def test_book_unlinked_row(client):  # → booking with the row's amount and date, confirmed; booking it again → 400
def test_german_difference_item(client):  # Accept-Language de → "Differenz"
```

- [ ] **Step 2: Run** — Expected: FAIL (404 on the routes).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: receipts fit the bank amount; bank lines are linked by hand`

### Task 4: Matching in the bank import

**Files:**
- Modify: `backend/app/reconcile.py`, `backend/app/import_api.py` (`check_file`, `run_import`, `balances`, preview
  route)
- Test: `tests/test_bank_matching.py`

**Interfaces:**
- Produces:
  - `reconcile.candidates_for_line(db, account, day: date, signed_amount: float, exclude: set[str]) ->
    list[models.Transaction]` — bookings on the account without bank rows, same sign, `|amount − line| <= TOLERANCE`,
    Swiss date in `[day − 30, day + 3]`, not in `exclude`; sorted exact amount first, then by distance in days.
  - Preview rows of a bank file (status ok, not duplicate) get `"matches": [{"id", "description", "date",
    "amount"}]` (all candidates) and `"match": id | None` (the chosen one: the form field `matches` — JSON
    `{line: id | "new"}` — else the first candidate not taken by an earlier line). A row with a match keeps status ok.
  - `run_import`: a row with a match creates no booking; its BankRow links to the matched booking, then
    `reconcile.fit`. An id in `matches` that isn't among the row's candidates → 400 `match_unknown` "Line {line}: that
    booking can't be confirmed by it" / "Zeile {line}: Diese Buchung kann sie nicht bestätigen".
  - `balances()` `app_balance`: the account's confirmed bookings (with bank rows) plus every ok row's signed amount
    (new or matched).

- [ ] **Step 1: Write the failing tests**

```python
def test_line_confirms_receipt(client):  # receipt booked 2026-09-03 −84.30 (items); line 2026-09-05 −84.30 → preview match = receipt; import → no new booking, receipt confirmed, balance −84.30
def test_tolerance(client):  # line −85.00 matches receipt −84.30 → import: amount −85.00, difference item 0.70
def test_no_match_outside_window_or_sign(client):  # receipt 2026-08-01, line 2026-09-05 → no match; income line doesn't match an expense
def test_candidate_used_once(client):  # one receipt, two equal lines → first line matches, second has match None
def test_choose_new_or_other(client):  # two receipts fit; matches {"2": "new"} → new booking; {"2": other_id} → that one
def test_unknown_match_refused(client):
def test_settle_up_booking_matched(client):  # a settle-up transfer (out) is confirmed by its bank line
def test_balance_check_confirmed_only(client):  # an unconfirmed booking on the account doesn't count in app_balance
```

- [ ] **Step 2: Run** — Expected: FAIL (no `match`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file, `tests/test_bank_import.py`, and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: a bank line confirms the booking it paid`

### Task 5: A receipt onto an existing bank booking

**Files:**
- Modify: `backend/app/reconcile.py`, `backend/app/api.py`
- Test: `tests/test_receipt_matching.py`

**Interfaces:**
- Produces:
  - `reconcile.payments_for_receipt(db, account, day: date, total: float) -> list[models.Transaction]` — expense
    bookings on the account with bank rows and no items, `| |amount| − total | <= TOLERANCE`, bank line dated in
    `[day − 3, day + 30]`; sorted like `candidates_for_line`.
  - `GET /accounts/{id}/payments?date=YYYY-MM-DD&total=84.30` (write access) → annotated bookings.
  - Putting a receipt on one is the existing `PUT /transactions/{id}` with `items`, `date`, `description`,
    `attachment_ids`: `update_receipt` already calls `fit` (Task 3), so the amount stays the bank's and the
    category becomes the items'.

- [ ] **Step 1: Write the failing tests**

```python
def test_payments_for_receipt(client):  # imported line 2026-09-05 −84.30 (Unsorted) → GET payments date 2026-09-03 total 84.30 lists it; date 2026-08-01 doesn't; total 90 doesn't
def test_receipt_onto_payment_keeps_balance(client):  # PUT items 83.40 + attachment → amount −84.30, category = items', date = receipt's, confirmed, receipt_missing False
def test_payments_need_write_access(client):
```

- [ ] **Step 2: Run** — Expected: FAIL (404).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: a receipt can go onto the bank booking that paid it`

### Task 6: Frontend and browser test

**Files:**
- Modify: `frontend/src/accounts.ts` (types), `frontend/src/components/Transactions.tsx`,
  `frontend/src/components/AccountCards.tsx`, `frontend/src/components/ImportTransactions.tsx`,
  `frontend/src/components/ReceiptForm.tsx`, `frontend/src/locales/{en,de}.ts`
- Create: `e2e/tests/reconciliation.spec.ts`

**Interfaces:**
- Consumes: Tasks 2–5 fields and endpoints.
- Produces (UI):
  - Transactions: badge per state — "not confirmed" (grey), "no payment found", "receipt missing", "partly paid: CHF
    x of y", "receipt and payment differ by CHF x" (amber) with an "accept" button; nothing for confirmed. The
    expanded part also lists bank rows (date, text, amount) with "unlink", and "link bank line" (select of unlinked
    rows of the account). A booking with bank rows expands even without items. A toggle "open points (N)" shows only
    open ones and, above them, "bank lines without booking" with "book" (category select) and "link" (booking select).
    A checkbox "receipt expected" in the expanded part.
  - AccountCards: for an account with states, "of which not confirmed: CHF x" and "N open points".
  - ImportTransactions: a row with `matches` shows a select "confirms: <description>, <date>, CHF x" / other
    candidates / "new booking"; the choice goes in the `matches` form field of later previews and the import.
  - ReceiptForm (new receipt on an account): once date and items total are set, `GET payments`; when found, an
    option list "add to the bank booking <text>, <date>, CHF x" (default: none = new booking); saving with one chosen
    PUTs onto it.

- [ ] **Step 1: Write the failing browser test** `e2e/tests/reconciliation.spec.ts`:

```ts
test('receipt confirmed by the bank statement', ...)
// account with IBAN; a receipt typed in: "Muster Laden", 2026-09-03, items 50.00 + 34.30 → no badge yet (no import on the account)
// import a statement: line 2026-09-02 "Einkauf TWINT Muster Laden" −84.30 and line 2026-09-20 "Zahlung Beispiel" −10
//   → preview row 2 "confirms: Muster Laden"; import 2 → receipt booking has no badge (confirmed) and shows its bank line when expanded
// a booking typed in on 2026-09-01 without bank line → badge "no payment found"; "open points (1)" toggle lists it
// a second statement line −20 "Einkauf TWINT Beispiel Shop" with rule "BEISPIEL SHOP" receipt expected → badge "receipt missing"
```

- [ ] **Step 2: Run** `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npx playwright test reconciliation` — Expected: FAIL.
- [ ] **Step 3: Implement** the components and texts (en + de).
- [ ] **Step 4: Run** the browser test, then all checks from Global Constraints — Expected: all PASS, 16 browser tests.
- [ ] **Step 5: Commit** `feat: confirmed, open and matched bookings in the app`
