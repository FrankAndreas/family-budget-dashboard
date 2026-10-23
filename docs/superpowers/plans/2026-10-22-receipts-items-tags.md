# Receipts, Items, Tags and Persons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read receipts (photo, PDF, `.eml`) with the Infomaniak AI into one booking with items; each item has a
category, tags and a person; budgets per tag; totals by tag and person; the receipt kept as an attachment.

**Architecture:** New tables for tags, items, item tags and attachments (migration 0008). `reports.py` counts
"spending lines" (one per plain booking, one per item) so budgets and Analytics never double count. Reading is a
backend endpoint (`receipt_ai.py`) that turns the file into AI input (`receipt_files.py`), calls the OpenAI-compatible
Infomaniak API through a replaceable client, and returns a draft; saving is the normal transaction API with `items`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest; new backend deps `pypdf`, `pypdfium2`, `Pillow`; React 19 +
react-i18next; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-22-receipts-items-tags-design.md`

## Global Constraints

- Secrets: `INFOMANIAK_AI_TOKEN`, `INFOMANIAK_AI_PRODUCT_ID` never in the repo, logs, error messages or responses; error
  messages name only the API path (`/chat/completions`), never the URL with the product ID. Locally they come from
  `pass andreas/infomaniak_ai_api_token` / `pass andreas/infomaniak_ai_product_id`; nobody prints them.
- Only the file's content, the EXPENSE category names and the tag names go to the AI. Nothing is booked without the
  person confirming.
- Config (env): `INFOMANIAK_AI_TOKEN`, `INFOMANIAK_AI_PRODUCT_ID`, `RECEIPT_AI_MODEL` (default
  `google/gemma-4-31B-it`), `RECEIPT_AI_READS_PER_HOUR` (default 30, same for every person, `0` = reading off),
  `ATTACHMENTS_DIR` (default: `attachments/` next to the SQLite file).
- API base `https://api.infomaniak.com/2/ai/<product_id>/openai/v1`, `Authorization: Bearer <token>`, temperature 0,
  timeout 60 s.
- Limits: upload 10 MB; ≤ 100 items per booking; item name ≤ 120 chars; tag name ≤ 50 chars, unique ignoring case;
  PDFs: ≤ 5 pages rendered.
- Counting: an item counts in full under **each** of its tags, once in its category, once in the totals; tag totals
  are never summed.
- New backend deps pinned exactly, each the newest release published before 2026-10-08 (two weeks); same for any new
  npm package (none planned).
- All visible text in `de.ts`/`en.ts` (check-texts) and errors in `app/messages.py` (both languages, Swiss spelling,
  du-form); dates via `format.ts`.
- Tests never call the real AI: `receipt_ai.client` is replaced; the e2e backend uses `RECEIPT_AI_FAKE=1`.
- Tools (scratch venv `V=/tmp/claude-1000/-home-andreas-work-family-budget-dashboard/bddd66bf-d388-43ab-9697-f451f8c8ad58/scratchpad/venv/bin`):
  `$V/pytest tests -q -p no:warnings`; from `backend/`: `$V/black --check app ../tools ../tests`,
  `$V/flake8 app ../tools --max-line-length=120 --extend-ignore=E203,W503`, `$V/mypy app/ ../tools/
  --ignore-missing-imports`; `cd frontend && npm run lint && npm run type-check && npm run build`;
  `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npm test`. Install new deps into both venvs
  (`$V/pip install …`, `.venv-e2e/bin/pip install …`).

## Review Focus

1. Deleting an account or a family member that has itemized bookings with attachments (bulk deletes in `crud`) →
   items, item tags and attachment rows go with them, the files are removed by the sweep. Test in Task 1 and Task 6.
2. An itemized booking edited through the old path (`PUT` with `amount`/`category_id` but no `items`) → refused with
   a clear message instead of silently desyncing amount and items. Test in Task 3.
3. AI answers with amounts as strings (`"3.50"`, `"3,50"`, `"CHF 3.50"`), negative discount lines, or extra prose
   around the JSON → parsed; anything else → that item amount 0 and flagged in `difference`. Test in Task 8.
4. A file renamed to `.jpg` that isn't an image, or an HTML mail with scripts → type decided by content (magic bytes /
   MIME parse), never rendered as HTML; served with `nosniff`. Test in Task 6.
5. A shared (split) receipt: changing its items changes the amount, and the common balance follows from the stored
   `split_shares` as today. Test in Task 3.

---

## File Structure

Backend (`backend/app/`):
- `models.py` — `Tag`, `TransactionItem`, `TransactionItemTag`, `Attachment`; `Budget.tag_id`; relationships.
- `migrations/versions/0008_receipt_items.py` — the new tables and `budgets.tag_id`.
- `tags_api.py` (new) — tags CRUD, usage.
- `items.py` (new) — validating and storing a booking's items, computing amount and main category.
- `reports.py` — spending lines; tag budgets; by tag / by person.
- `attachments.py` (new) — storing, serving, linking and sweeping attachment files; type detection.
- `receipt_files.py` (new) — file → AI content parts (image, PDF text/pages, e-mail text).
- `receipt_ai.py` (new) — config, AI client, prompt, answer parsing, rate limit, `/receipts/*` endpoints.
- `api.py`, `schemas.py`, `crud.py`, `categories_api.py`, `export_api.py`, `export_readme.md`, `messages.py`,
  `main.py` (routers, sweep on start).

Frontend (`frontend/src/`):
- `components/TagManager.tsx` (new) — Settings → Tags.
- `components/ReceiptForm.tsx` (new) — upload, AI draft, item editor, attachments; used for new and existing bookings.
- `receipts.ts` (new) — types and API calls for items, tags, attachments, reading.
- `components/Transactions.tsx`, `BudgetManager.tsx`, `Analytics.tsx`, `pages/dashboard/Dashboard.tsx`,
  `locales/de.ts`, `locales/en.ts`.

Other: `backend/requirements.txt`, `docker-compose.yml`, `.env.example`, `README_DOCKER.md`, `README.md`,
`scripts/dev-backend.sh` (new), `e2e/playwright.config.ts`, `e2e/tests/receipts.spec.ts` (new), `tests/files/` helpers.

---

### Task 1: Data model and migration 0008

**Files:** Modify `backend/app/models.py`; Create `backend/app/migrations/versions/0008_receipt_items.py`;
Test `tests/test_receipt_model.py`.

**Interfaces — Produces:**
- `models.Tag(id, name, icon)`;
  `models.TransactionItem(id, transaction_id, position, name, amount: Money, category_id, person_id)` with
  `tags: list[Tag]` (secondary `transaction_item_tags`) and `category`;
  `models.Attachment(id, transaction_id: Optional, owner_id, filename, content_type, size, sha256, created_at)`;
  `models.Transaction.items` (ordered by `position`, `cascade="all, delete-orphan"`), `models.Transaction.attachments`;
  `models.Budget.tag_id: Optional[str]` (and `category_id` becomes optional in the model).
- FKs: `transaction_items.transaction_id` and `attachments.transaction_id` `ondelete="CASCADE"`;
  `transaction_item_tags.item_id`/`tag_id` `ondelete="CASCADE"`; `transaction_items.person_id` `ondelete="SET NULL"`;
  `attachments.owner_id` → users (who uploaded; pending attachments belong to them), `ondelete="CASCADE"`.

- [ ] **Step 1: Failing tests** — `tests/test_receipt_model.py`:
  - `test_database_matches_the_models` is already covered by `tests/test_database.py::…test_empty_database_matches_the_models`; run it after the change.
  - `test_deleting_a_booking_deletes_its_items_tags_and_attachment_rows`: create a transaction with two items (one
    with two tags) and one attachment row via the session; delete the transaction; assert counts of items, item-tag
    rows and attachments are 0 and both tags still exist.
  - `test_deleting_an_account_with_itemized_bookings`: `DELETE /accounts/{id}` on an account with an itemized booking
    → 200, items gone (crud's bulk delete must not trip the FK).
  - `test_removing_a_person_clears_their_items`: an item with `person_id` = a dependent child; delete the child via
    the API (`DELETE /users/{id}` with `{"items": []}`) → the item stays with `person_id` None.
- [ ] **Step 2:** `$V/pytest tests/test_receipt_model.py -q` → FAIL (no such models).
- [ ] **Step 3:** Models + migration 0008 (`down_revision = "0007"`; create the four tables; `budgets.tag_id` with
  `batch_alter_table`; downgrade drops them). SQLite FK cascades need `PRAGMA foreign_keys=ON`, already on.
- [ ] **Step 4:** Run the new tests and `tests/test_database.py` → PASS.
- [ ] **Step 5:** Full suite, lint, mypy; commit `feat: tables for receipt items, tags and attachments (#56)`.

### Task 2: Tags API

**Files:** Create `backend/app/tags_api.py`; Modify `schemas.py`, `main.py`, `messages.py`; Test `tests/test_tags.py`.

**Interfaces — Produces:** `GET /api/v1/tags` → `[{id, name, icon}]` sorted by name (everyone logged in);
`GET /api/v1/tags/usage` → `{tag_id: {"items": n, "budgets": n}}`; `POST /api/v1/tags` `{name, icon?}`;
`PUT /api/v1/tags/{id}` `{name?, icon?}`; `DELETE /api/v1/tags/{id}` (removes it from items; refused with 409 while a
budget uses it). Create/update/delete parents only. `schemas.Tag`, `schemas.TagCreate`, `schemas.TagUpdate`.

- [ ] **Step 1: Failing tests**: create/list sorted; name trimmed, 1–50 chars; duplicate ignoring case → 400
  `tag_name_taken`; child with login → 403 `only_parents_tags`; rename; delete removes the tag from an item that keeps
  its other tag; delete while a budget uses it → 409 `tag_in_budget`; usage counts; German message for a duplicate
  (person language `de`).
- [ ] **Step 2:** run → FAIL. **Step 3:** implement, following `categories_api.py`. Messages (de/en) for the three
  keys. **Step 4:** PASS. **Step 5:** suite, lint; commit `feat: tags (#56)`.

### Task 3: Items on bookings

**Files:** Create `backend/app/items.py`; Modify `schemas.py`, `api.py`, `crud.py`, `categories_api.py`,
`messages.py`; Test `tests/test_items.py`.

**Interfaces:**
- `schemas.ItemIn(name: str 1..120 stripped, amount: float ≠ 0, category_id: str, person_id: Optional[str] = None,
  tag_ids: list[str] = [])`; `schemas.ItemOut(id, position, name, amount, category_id, person_id, tag_ids)`.
- `TransactionCreate.items: Optional[list[ItemIn]] = None` (max 100); `TransactionUpdate.items` the same;
  `schemas.Transaction.items: list[ItemOut] = []`. `TransactionCreate.category_id` and `.amount` become optional and
  are required only when `items` is absent (validator).
- `items.apply(db: Session, user: models.User, transaction: models.Transaction, items: list[schemas.ItemIn]) -> None`
  — validates (EXPENSE categories, tags exist, person exists and `privacy.access_level(db, user, person)` is not None
  or person is the user, sum of amounts > 0), replaces the items (positions 0..n-1), sets
  `transaction.amount = -sum` (cents) and `transaction.category_id` = category with the largest item sum (ties: first
  item's category), clears `transaction.member_id`.
- Messages: `items_need_expense_category`, `item_tag_not_found`, `item_person_not_found`, `items_sum_positive`,
  `edit_items_instead`.

- [ ] **Step 1: Failing tests** (`tests/test_items.py`), each via the HTTP API:
  - `test_receipt_with_items`: POST with items [Brot 3.50 Lebensmittel, Velo-Hose 79.90 Kleidung tags [Velo]] →
    amount −83.40, `category_id` = Kleidung, items returned in order with tag ids.
  - `test_main_category_is_the_largest_sum`, `test_discount_line_lowers_the_amount` (item −2.00), `test_sum_must_be_positive`.
  - `test_items_need_expense_categories` (Salary → 400), unknown tag/person → 400, person the caller can't see → 400.
  - `test_put_replaces_items`; `test_put_empty_items_makes_a_plain_booking` (needs `amount` and `category_id`).
  - `test_old_edit_on_itemized_booking_is_refused`: PUT `{"amount": 5}` without `items` → 400 `edit_items_instead`;
    PUT `{"description": "x"}` alone → 200 (description and date may change).
  - `test_shared_receipt_follows_items` (Review Focus 5): itemized booking with a split; PUT new items; GET
    `/common/balance` reflects the new amount.
  - `test_category_used_by_items_cannot_be_deleted` (`usage_counts` counts items under a new key `items` with its
    plural messages `used_items_one/_other` in both languages).
  - `test_items_listed_with_transactions`: `GET /accounts/{id}/transactions` returns `items`.
- [ ] **Step 2:** FAIL. **Step 3:** implement; transfers (TRANSFER categories) can't have items. **Step 4:** PASS.
- [ ] **Step 5:** suite (existing tests must stay unchanged), lint, mypy; commit `feat: bookings with items (#56)`.

### Task 4: Counting by lines; tag budgets; by tag and person

**Files:** Modify `backend/app/reports.py`, `schemas.py`, `api.py` (budgets), `crud.py`, `messages.py`;
Test `tests/test_item_reports.py`.

**Interfaces:**
- `reports.Line` (dataclass: `date: datetime, amount: float (positive), type: CategoryType, category: Category,
  person_id: Optional[str], tag_ids: frozenset[str], member_id: Optional[str]`).
- `reports.lines(db, owner_id: str, since: Optional[date]) -> list[Line]` replaces `bookings`: a plain booking → one
  line (its category, `member_id`); an itemized booking → one line per item (item category, `person_id`, tags).
- `budget_out` and `summary` use `lines`. `summary` gains `by_tag: [{tag_id, name, icon, amount}]` and
  `by_person: [{person_id, name, amount}]` (expenses only; sorted by amount desc). `by_child` counts a line when
  `member_id` or `person_id` is a dependent child.
- Budgets: `BudgetCreate.category_id: Optional`, `tag_id: Optional`, exactly one (422 otherwise);
  `schemas.Budget.tag_id`; `budget_out` sums lines carrying the tag for a tag budget.

- [ ] **Step 1: Failing tests** (`tests/test_item_reports.py`):
  - `test_item_with_two_tags_counts_in_each_tag_once_in_category_and_total`: one receipt, items A 80.00 Kleidung
    tags [Velo, Sport], B 20.00 Lebensmittel no tag → `by_tag` Velo 80, Sport 80; `by_category` Kleidung 80,
    Lebensmittel 20; `expenses` 100.
  - `test_category_budget_counts_items` (Kleidung budget spent 80, not 100);
    `test_tag_budget_counts_items_with_the_tag` (Velo yearly budget spent 80); `test_budget_needs_exactly_one_of_category_or_tag`.
  - `test_by_person` and `test_child_costs_include_items_for_a_dependent_child`.
  - `test_plain_bookings_unchanged`: the existing report tests keep passing (run `tests/test_reports.py`).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** suite, lint, mypy; commit
  `feat: budgets and analytics count items; tag budgets (#56)`.

### Task 5: Analysis export

**Files:** Modify `backend/app/export_api.py`, `export_readme.md`; Test `tests/test_export.py` (extend).

- [ ] **Step 1:** Failing test `test_items_and_tags_in_the_zip`: `items.csv` header exactly
  `item_id,transaction_id,position,name,amount,category_id,category,person_id,person,tags` with tags `;`-joined names;
  `tags.csv` header `tag_id,name,icon`; only items of bookings the caller may see; README mentions both files.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat: items and tags in the analysis export (#56)`.

### Task 6: Attachments

**Files:** Create `backend/app/attachments.py`; Modify `api.py` (transaction create accepts `attachment_ids`),
`schemas.py`, `main.py`, `messages.py`; Test `tests/test_attachments.py`.

**Interfaces:**
- `attachments.detect(data: bytes, filename: str) -> Optional[str]` → `image/jpeg` (`FF D8 FF`), `image/png`
  (`89 50 4E 47`), `application/pdf` (`%PDF-`), `message/rfc822` (`.eml` name and `email.message_from_bytes` finds
  a `From` or `Subject` header); else None.
- `attachments.store(db, owner: User, filename: str, data: bytes, transaction_id: Optional[str]) -> Attachment`
  (writes `ATTACHMENTS_DIR/<id>`, sha256, size; 400 `file_too_large` > 10 MB, 400 `file_type_unsupported`).
- `attachments.link(db, user, transaction, ids: list[str])` — only the user's own pending ones.
- `attachments.sweep(db) -> int` — deletes pending rows older than 24 h and files without a row; runs on start
  (`main.py`) and every 24 h (asyncio task started on app start).
- Endpoints: `POST /api/v1/transactions/{id}/attachments` (multipart `file`; write access to the booking);
  `GET /api/v1/attachments/{id}` (view access to the booking, or own pending) → file with its stored type,
  `Content-Disposition: inline` for images and PDFs, `attachment` for e-mails, `X-Content-Type-Options: nosniff`;
  `DELETE /api/v1/attachments/{id}` (write access). `schemas.Transaction.attachments: [{id, filename, content_type, size}]`.

- [ ] **Step 1: Failing tests:** store and fetch a PNG (bytes equal, headers as above); a `.jpg` that is text → 400
  (Review Focus 4); `.eml` served as `attachment`; 10 MB + 1 → 400; someone without access → 404; pending
  attachment linked on create; another person's pending id → 400; delete booking → row gone, file removed by
  `sweep`; `sweep` removes 25 h old pending, keeps 23 h old; deleting an account with an attached booking works
  (Review Focus 1). Use `ATTACHMENTS_DIR` = `tmp_path` via a fixture in `tests/conftest.py`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → suite, lint, mypy → commit `feat: receipt attachments (#56)`.

### Task 7: Turning a file into AI input

**Files:** Create `backend/app/receipt_files.py`, `tests/files.py` (builders for test files); Modify
`backend/requirements.txt`, `tests/requirements.txt` if it lists backend deps; Test `tests/test_receipt_files.py`.

**Interfaces:** `receipt_files.ai_content(content_type: str, data: bytes) -> list[dict]` — OpenAI content parts:
image → `[{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,…"}}]` (shrunk to max 1600 px JPEG
with Pillow); PDF with text (`pypdf`, > 20 non-space chars) → `[{"type": "text", "text": …}]`; PDF without text →
up to 5 page images rendered with `pypdfium2` at 150 dpi; e-mail → body text (plain, else HTML stripped to text with
`html.parser`), or, if the text has no digit-comma/dot-digit amount, its first PDF/image attachment handled as above;
nothing usable → raises `receipt_files.Unreadable`.

- [ ] **Step 1: Failing tests** with files built in `tests/files.py` (no real receipts in the repo):
  `image_png(text)` (Pillow), `pdf_with_text(lines)` (minimal hand-written PDF with a text layer),
  `pdf_scanned()` (Pillow image saved as PDF), `eml(body_text=None, body_html=None, attach_pdf=None)` (stdlib
  `email`). Assert: image → one image part, ≤ 1600 px; text PDF → text part containing the line; scanned PDF → image
  parts (≤ 5); HTML mail with `<script>` → text without the script content; mail with a PDF attachment and an
  amount-less body → the PDF's text; empty mail → `Unreadable`.
- [ ] **Step 2:** FAIL. **Step 3:** add `pypdf`, `pypdfium2`, `Pillow` to `backend/requirements.txt` (pinned, see
  Global Constraints), install into both venvs, implement. **Step 4:** PASS. **Step 5:** commit
  `feat: read photos, PDFs and e-mails as AI input (#56)`.

### Task 8: Reading a receipt with the AI

**Files:** Create `backend/app/receipt_ai.py`; Modify `main.py`, `messages.py`, `schemas.py`; Test
`tests/test_receipt_ai.py`.

**Interfaces:**
- `receipt_ai.Settings` (from env, read per request so tests can monkeypatch): token, product_id, model,
  reads_per_hour; `enabled` = token and product_id set and reads_per_hour > 0.
- `class AiClient(Protocol): def complete(self, content: list[dict]) -> str`; `InfomaniakClient(settings)` (urllib,
  `POST {base}/chat/completions`, timeout 60 s; on HTTP/URL errors raises `AiUnavailable` with a message naming only
  `/chat/completions`); `FakeClient` (returns a fixed JSON receipt, used when `RECEIPT_AI_FAKE=1`).
  `receipt_ai.client_for(settings) -> AiClient` — tests monkeypatch this.
- `receipt_ai.prompt(categories: list[str], tags: list[str], lang: str) -> str` (de/en; asks for JSON
  `{shop, date, total, items:[{name, amount, category, tags}]}`, several tags allowed, leave out card numbers).
- `receipt_ai.parse(text: str, categories: dict[str, Category], tags: dict[str, Tag]) -> dict` → draft
  `{shop, date, total, items:[{name, amount, category_id, tag_ids}], difference}`: first `{…}` in the text; amounts
  accept `3.50`, `"3,50"`, `"CHF 3.50"`, negatives; unknown/invalid amount → 0; unknown category → Unsortiert (by
  `system_key`); unknown tags dropped; names cut to 120; ≤ 100 items; `difference` = total − sum (rounded, 0 if equal).
- Endpoints: `GET /api/v1/receipts/status` → `{"enabled": bool}`; `POST /api/v1/receipts/read` (multipart `file`) →
  `{"draft": …, "attachment_id": …}` (stores the file as a pending attachment via Task 6 first).
- Rate limit: per user, in memory, last-hour timestamps; over the limit → 429 `receipt_reads_used_up` with minutes
  until the next read.
- Messages: `receipt_ai_off`, `receipt_ai_unavailable`, `receipt_ai_unreadable`, `receipt_reads_used_up_one/_other`,
  `file_type_unsupported`, `file_too_large`.

- [ ] **Step 1: Failing tests:** status off without config / with `RECEIPT_AI_READS_PER_HOUR=0`; read with a fake
  client returning text with prose around JSON → draft mapped to ids; amounts as strings and with comma (Review
  Focus 3); unknown category → Unsortiert id; unknown tag dropped; difference; malformed answer → 502
  `receipt_ai_unreadable`; client raising `AiUnavailable` → 502 `receipt_ai_unavailable`; rate limit with
  `RECEIPT_AI_READS_PER_HOUR=2` → third read 429; **no secret leaks**: with token `tok-SECRET` and product
  `pid-SECRET`, a failing `InfomaniakClient` (urlopen monkeypatched to raise) → response text and `caplog` contain
  neither value; the prompt contains the category and tag names and nothing else from the database (assert on the
  content passed to the fake client).
- [ ] **Steps 2–5:** FAIL → implement → PASS → suite, lint, mypy → commit `feat: read receipts with the Infomaniak AI (#56)`.

### Task 9: Frontend — tags, tag budgets, analytics

**Files:** Create `frontend/src/components/TagManager.tsx`, `frontend/src/receipts.ts`; Modify `Dashboard.tsx`
(Settings: TagManager for parents, after CategoryManager), `BudgetManager.tsx`, `Analytics.tsx`, locales.

**Interfaces:** `receipts.ts`: `interface Tag {id; name; icon?}`, `useTags(): {tags, reload}`,
`interface Item {id?; name; amount; category_id; person_id?; tag_ids}`, `interface AttachmentInfo {id; filename;
content_type; size}`, `interface Draft {shop; date; total; items; difference}`.

- [ ] **Step 1:** TagManager like CategoryManager (add, rename, icon, delete with usage "used by n items / n budgets").
- [ ] **Step 2:** BudgetManager: the add form's select lists categories and, in a second optgroup "Tags", tags
  (value `tag:<id>`); a tag budget shows the tag icon + name.
- [ ] **Step 3:** Analytics: cards "Ausgaben nach Tag" (list, no sum, note `analytics.tagsOverlap`) and "Ausgaben nach
  Person", hidden when empty.
- [ ] **Step 4:** lint (incl. check-texts), type-check, build, all browser tests → pass. Commit
  `feat: tags, tag budgets and spending by tag and person in the app (#56)`.

### Task 10: Frontend — receipt form and item display

**Files:** Create `frontend/src/components/ReceiptForm.tsx`; Modify `Transactions.tsx`, `receipts.ts`, locales.

**Interfaces:** `<ReceiptForm account={Account} categories={Category[]} transaction?={Transaction} onSaved onCancel />`.

- [ ] **Step 1:** Transactions card: button "📷 Beleg" when `GET /receipts/status` is enabled **or** always "🧾 Positionen
  erfassen" (manual form without AI); itemized rows show "🧾 n Positionen" (expandable list: name, amount, category,
  tag chips, person) and "📎 n" links (images/PDF open in a new tab via an authenticated blob URL, e-mails download).
  ✎ on an itemized booking (or "In Positionen aufteilen" on a plain expense) opens ReceiptForm.
- [ ] **Step 2:** ReceiptForm: file input (`accept="image/*,application/pdf,.eml,message/rfc822"`, photos shrunk to
  1600 px JPEG with a canvas before upload); "Wird gelesen…" while `POST /receipts/read` runs; errors shown with
  `errorMessage`; then fields date, description (shop), person for all items, item rows (name, amount, category select
  of EXPENSE categories, tag multi-select, person select, ✕), "+ Position", sum / total / difference (red when ≠ 0);
  "Buchen" disabled while the sum ≤ 0; saves via POST/PUT with `items` and `attachment_ids`.
- [ ] **Step 3:** lint, type-check, build, browser tests. Commit `feat: receipt form with items, tags and persons (#56)`.

### Task 11: Configuration, docs, end-to-end test

**Files:** Modify `docker-compose.yml`, `.env.example`, `README_DOCKER.md`, `README.md`, `e2e/playwright.config.ts`;
Create `scripts/dev-backend.sh`, `e2e/tests/receipts.spec.ts`.

- [ ] **Step 1:** Compose passes the five env values (empty = off); `.env.example` documents them (no values);
  README_DOCKER: setting up the token (scope `ai-tools`, lifetime, spending cap), outgoing HTTPS from the NAS,
  `data/attachments` and that the NAS backup of `data/` must include it; README: local start.
- [ ] **Step 2:** `scripts/dev-backend.sh`: exports `INFOMANIAK_AI_TOKEN="$(pass show andreas/infomaniak_ai_api_token | head -1)"`
  and the product ID the same way, then starts uvicorn; `set +x`, prints nothing about the values.
- [ ] **Step 3:** e2e backend env `RECEIPT_AI_FAKE=1`, `INFOMANIAK_AI_TOKEN=fake`, `INFOMANIAK_AI_PRODUCT_ID=fake`.
  `receipts.spec.ts`: upload a generated PNG → draft items appear → give one item the tags Velo and Sport → Buchen →
  the booking shows "🧾 2 Positionen" and 📎 → Analytics shows Velo and Sport with the same amount; a Velo budget
  shows it as spent.
- [ ] **Step 4:** full checks (pytest, black, flake8, mypy, frontend, all e2e). Commit
  `feat: receipt setup docs and browser test (#56)`.
