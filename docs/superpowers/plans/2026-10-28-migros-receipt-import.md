# Migros Receipt Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upload the Cumulus "Kassenbeleg" CSV in the app: one booking per receipt with its articles as lines, put
onto the bank payment that paid it, each article categorised and tagged by article rule → AI → fallback, the booked
result learnt as rules.

**Architecture:** A parser (`migros_csv.py`) turns the file into receipts; article rules get their own table and API
(`article_rules.py`); a text-only AI call suggests categories and tags (`receipt_ai.suggest_articles`); a separate
preview/import pair (`migros_import.py`, `/import/migros/...`) next to the bank import, stateless like it: the
frontend sends its choices back with the file. The import UI recognises the file by its header and shows
`MigrosImport.tsx` instead of the row preview.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite; React 19, TS, Tailwind, react-i18next; pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-migros-receipt-import-design.md`

## Global Constraints

- Repository is public: tests use invented articles and stores only (e.g. "Filiale Muster", "Brot", "Zahnpasta"),
  never the user's export.
- Header recognised: `Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz` (UTF-8 with or
  without BOM, or Windows-1252, via `bank_csv.decode`).
- Receipt key: `migros:<Datum>:<Zeit>:<Filiale>:<Kassennummer>:<Transaktionsnummer>`, stored in
  `transactions.reference`.
- Amount tolerance CHF 1.00 (`reconcile.TOLERANCE`); payment window receipt −3 to +30 days
  (`reconcile.payments_for_receipt`).
- AI: only article names plus category and tag names are sent; one call per file; at most `MAX_TEXTS` (200) names.
- Fallback category: the default category with `default_key` `GROCERIES`; no tags; no rule learnt from a fallback.
- Article rules match the whole name, ignoring case and surrounding spaces.
- Migration 0020, additive; `database_setup.HEAD = "0020"`.
- Parents only for the Migros preview and import and for article rules (403 otherwise).
- German and English for every new text (`npm run lint` checks both locale files have the same keys).
- Component files export only components (react-refresh lint); helpers go in `frontend/src/migros.ts`.

## Review Focus

- A receipt whose lines sum to 0 or less (only vouchers, or a return) → shown as an error receipt that can't be
  ticked; the rest of the file still imports. (Task 4 test `test_receipt_not_positive_is_an_error`)
- Two receipts in one file with the same total on the same day → each claims a different bank booking, never the
  same one. (Task 4 test `test_two_receipts_never_share_a_payment`)
- An article written with different case or spaces across receipts ("Brot", "brot ") → one rule, one AI question.
  (Task 2 and Task 4 tests)
- An article that already has a rule, changed in the preview → the rule is updated to what was booked (my ruling:
  "what was booked becomes the rule"). (Task 4 test `test_changed_article_updates_its_rule`)
- A failed import (an error during booking) → no rules saved, no booking made. (Task 4 test
  `test_failed_import_saves_nothing`)

---

### Task 1: Read the Migros file

**Files:**
- Create: `backend/app/migros_csv.py`
- Test: `tests/test_migros_csv.py`

**Interfaces:**
- Produces:
  - `HEADER: str` (the header above)
  - `is_migros(text: str) -> bool` (first line, after BOM and spaces, equals `HEADER` ignoring case)
  - `@dataclass Line: name: str; amount: float` (CHF, rounded to cents; negative for a voucher)
  - `@dataclass Receipt: key: str; when: datetime` (naive, Swiss local time) `; store: str; lines: list[Line]` and
    property `total -> float` (cents-rounded sum)
  - `receipts(text: str) -> list[Receipt]` newest first; raises `messages.api_error(400, "migros_line_invalid",
    line=n)` for a row with a bad date, time or amount

- [ ] **Step 1: Write the failing tests** (invented data only)
  - `test_is_migros`: header with BOM and CRLF → True; a bank header → False.
  - `test_receipts_grouped_and_cleaned`: a file with two receipts (different Transaktionsnummer, same day):
    - `Karotten;2;0.00;3.90`, `Karotten;-2;0.00;-3.90`, `Karotten;1;0.00;1.95` → one line `Karotten 1.95`.
    - `Brot;1;0.00;3.50` and `brot ;1;0.00;3.50` in one receipt → one line `Brot 7.00` (first spelling kept, names
      compared ignoring case and spaces).
    - `Bonus-Coupon 2x;1;0;0` and `CUM10x Pkt Brot;1;0;0` → dropped.
    - `CUMULUS BON 5.-;0;0;-5.00` → kept as a line with amount −5.00.
    - `Milch;0.424;0.10;1.95` (weight) → 1.95.
    - assert keys `migros:12.09.2026:11:35:25:Filiale Muster:270:133`, `when == datetime(2026, 9, 12, 11, 35, 25)`,
      totals, order newest first.
  - `test_bad_amount_names_the_line`: `Umsatz` `abc` on CSV line 3 → 400 whose detail names line 3.

- [ ] **Step 2: Run, expect FAIL** — `cd backend && pytest -q -p no:warnings ../tests/test_migros_csv.py` →
  ModuleNotFoundError `app.migros_csv`.

- [ ] **Step 3: Implement** with `csv.reader(delimiter=";")`, `Decimal` for amounts; add the message
  `migros_line_invalid` (en/de) to `backend/app/messages.py`.

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** `feat(migros): read the Cumulus receipt export`.

### Task 2: Article rules (table, API, tags, categories, export)

**Files:**
- Create: `backend/app/article_rules.py`, `backend/app/migrations/versions/0020_article_rules.py`
- Modify: `backend/app/models.py` (`ArticleRule`, `ArticleRuleTag`), `backend/app/database_setup.py` (HEAD),
  `backend/app/main.py` (router), `backend/app/tags_api.py` (usage `article_rules`, delete removes links),
  `backend/app/categories_api.py` (`USERS` + messages `used_article_rules_one/_other`), `backend/app/export_api.py`
  (`article_rules.csv`: `rule_id,name,category_id,category,tag_ids,tags`, tags `;`-joined),
  `backend/app/export_readme.md`, `backend/app/messages.py`
- Test: `tests/test_article_rules.py`, plus the export header test in `tests/test_export.py`

**Interfaces:**
- Produces:
  - `models.ArticleRule`: `id, name (str), category_id (FK categories), created_at`, relationship `tags` (secondary
    `article_rule_tags`, ordered by name), property `tag_ids -> list[str]`
  - `article_rules.norm(name: str) -> str` (strip + casefold)
  - `article_rules.load(db) -> dict[str, models.ArticleRule]` keyed by `norm(name)`
  - `article_rules.learn(db, name: str, category: models.Category, tags: list[models.Tag]) -> None` (creates or
    updates the rule for `norm(name)`; caller commits)
  - API (parents only, 403 `only_parents_import_rules`, reusing `import_rules.require_parent`): `GET /article-rules?q=` (sorted by name,
    `q` filters by substring ignoring case), `POST /article-rules`, `PUT /article-rules/{id}`,
    `DELETE /article-rules/{id}`; body `{name, category_id, tag_ids}`; out `{id, name, category_id, category,
    tag_ids}`; 400 `article_rule_taken` when the normalised name exists, 400 `items_need_expense_category` for a
    non-expense category, 400 `tag_not_found`.
  - `GET /tags/usage` rows gain `"article_rules": n`.

- [ ] **Step 1: Write the failing tests**
  - `test_crud_and_search`: create "Zahnpasta" → Healthcare with tag Kinder; `GET ?q=zahn` lists it; "zahnpasta "
    again → 400; PUT changes category; DELETE removes it; a child gets 403.
  - `test_learn_updates_by_normalised_name`: `learn("Brot", Groceries, [])` then `learn(" brot", Other Expense,
    [tag])` → one rule, name "Brot", Other Expense, the tag.
  - `test_tag_delete_and_usage`: usage counts the rule; deleting the tag leaves the rule without it.
  - `test_category_in_use`: category usage shows `article_rules: 1` (as for import rules).
  - `test_migration_0020_up_and_down` (pattern of `tests/test_asset_tags.py::test_migration_keeps_the_tag`).
  - `tests/test_export.py`: `article_rules.csv` in the ZIP with the header above.

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** (model, migration, module, hooks).
- [ ] **Step 4: Run** the new tests and the full backend suite, black, flake8, mypy → all pass.
- [ ] **Step 5: Commit** `feat(migros): article rules with category and tags`.

### Task 3: AI suggestions for articles

**Files:**
- Modify: `backend/app/receipt_ai.py`
- Test: `tests/test_article_ai.py`

**Interfaces:**
- Produces: `receipt_ai.suggest_articles(db, user, names: list[str]) -> tuple[dict[str, dict], str, Optional[str]]`
  — `{name: {"category_id": str, "tag_ids": list[str]}}`, status `off|ok|capped|limit|failed` and message, exactly
  like `suggest` (one read via `take_read`; `AiUnavailable`/bad JSON → `failed`; > `MAX_TEXTS` → `capped`). Unknown
  category or tag names in the answer are dropped; categories only from `plain_categories(EXPENSE)`.
  - Prompt: `ARTICLE_PROMPTS[lang]` + `ARTICLE_MARKER` + JSON list of names; answer
    `{name: {"category": ..., "tags": [...]}}`.
  - `FakeClient`: for `ARTICLE_MARKER` answers every name "Groceries" with no tags, except names containing
    "zahn" (any case) → "Healthcare" (so browser tests see the AI decide).

- [ ] **Step 1: Write the failing tests** with a fake client (pattern of `tests/test_scans.py::ai`):
  `test_names_and_categories_only_are_sent` (question has the names and category names, no amounts),
  `test_unknown_names_dropped`, `test_off_and_failed`, `test_counts_one_read`.
- [ ] **Step 2: Run, expect FAIL.**  **Step 3: Implement.**  **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(migros): AI suggests categories and tags for articles`.

### Task 4: Preview and import

**Files:**
- Create: `backend/app/migros_import.py`
- Modify: `backend/app/main.py` (router), `backend/app/messages.py`
- Test: `tests/test_migros_import.py`

**Interfaces:**
- Consumes: Task 1 `receipts`, `is_migros`; Task 2 `load`, `learn`, `norm`; Task 3 `suggest_articles`;
  `reconcile.payments_for_receipt`, `reconcile.fit`, `items.apply`, `api.create_receipt`'s way of booking,
  `privacy.get_accessible_accounts` + `privacy.check_account_access(write=True)`.
- Produces:
  - `POST /import/migros/preview` form fields `file`, `choices` (JSON, optional), `ai` ("1" on the first preview)
  - `POST /import/migros` form fields `file`, `choices`
  - `choices`: `{"articles": {norm_name: {"category_id", "tag_ids", "source"}}, "receipts": {key: {"include":
    bool, "payment": booking_id | "new", "account_id": str}}}`
  - preview out: `{"receipts": [{key, date, time, store, total, status: "new"|"imported"|"maybe_booked"|"error",
    error, include, payments: [{id, description, date, amount}], payment, account_id, lines: [{name, amount,
    category_id, tag_ids, source: "rule"|"ai"|"change"|"fallback"}]}], "articles": {norm_name: {category_id,
    tag_ids, source}}, "accounts": [{id, name}], "new_rules": n, "ai": {status, message} | null}`
  - import out: `{"onto_payments": n, "booked": n, "rules": n}`

Rules decided here (from the spec):
- Article source order: `change` (from choices with source "change") → `rule` → `ai` (choices with source "ai", or the
  first preview's call) → `fallback`.
- Rules learnt on import for every booked article whose source is `change` or `ai` (a `change` on an article with a
  rule updates it); never from `fallback` or an unchanged `rule`.
- Payments searched on accessible accounts the importer may write, excluding bookings claimed by an earlier receipt
  in the file (newest receipt first); default `payment` = first candidate, else "new".
- `account_id` default for "new": the account of the latest receipt matched in this file, else the importer's first
  own BANK account; must be writable (403 otherwise).
- `imported`: a transaction with the key as `reference` exists → not includable. `maybe_booked`: a booking with
  items on an accessible account, same Swiss day, total within TOLERANCE, description containing "migros" (any
  case), reference not starting `migros:` → `include` false by default. `error`: total ≤ 0 → not includable.
- Onto a payment: `items.apply`, date = receipt time (Swiss → UTC), description `Migros <store>`, `reference` = key,
  then `reconcile.fit`. New: like `api.create_receipt` with `reference` = key, description `Migros <store>`.
  All receipts and rules in one transaction; any error → rollback.

- [ ] **Step 1: Write the failing tests** (invented file built in the test; a bank booking with a bank row made as
  in `tests/test_reconcile*.py`):
  - `test_preview_finds_the_payment_and_books_onto_it`: receipt (Brot 3.50, Zahnpasta 6.95, Karotten 1.95: total 12.40) on 12.09.; a bank
    booking −12.40 on 13.09. with a bank row → preview `payment` is its id; import → that booking has the lines, `reference` = key,
    description "Migros Filiale Muster"; `onto_payments == 1`.
  - `test_no_payment_books_new_and_bank_import_finds_it_later`: no bank booking → booked new on the default
    account; a later bank file line of −12.40 matches it (existing `match_bookings`).
  - `test_rule_then_ai_then_fallback`: rule for "Brot" → source rule; AI on → "Zahnpasta" Healthcare source ai;
    AI off → "Seife" Groceries source fallback; import learns "Zahnpasta" only; `new_rules == 1`.
  - `test_changed_article_updates_its_rule`: "Brot" has rule Groceries; choices change it to Other Expense with
    a tag → rule updated after import.
  - `test_reimport_is_already_imported` and `test_maybe_booked_is_unticked`.
  - `test_receipt_not_positive_is_an_error`: a receipt with only a voucher → status error; the other receipt imports.
  - `test_two_receipts_never_share_a_payment`: two receipts of 12.40 on the same day, two bank bookings −12.40 →
    different payments.
  - `test_failed_import_saves_nothing`: choices with an unknown `account_id` → 4xx, no booking, no rule.
  - `test_parents_only`: a child gets 403.
- [ ] **Step 2: Run, expect FAIL.**  **Step 3: Implement.**
- [ ] **Step 4: Run** the full backend suite, black, flake8, mypy → pass.
- [ ] **Step 5: Commit** `feat(migros): preview and import of the receipt export`.

### Task 5: Import screen and article rules in Settings

**Files:**
- Create: `frontend/src/migros.ts` (`isMigrosFile(file: File): Promise<boolean>` reading the first 200 bytes; the
  preview types), `frontend/src/components/MigrosImport.tsx`, `frontend/src/components/ArticleRules.tsx`
- Modify: `frontend/src/components/ImportTransactions.tsx` (Migros file → render `MigrosImport` with the file instead
  of the row preview), `frontend/src/components/DataManager.tsx` (ArticleRules for parents, under ImportRules),
  `frontend/src/locales/{de,en}.ts` (`migros.*`, `articleRules.*`)
- Test: `e2e/tests/migros-import.spec.ts`, `e2e/README.md`

**Interfaces:**
- Consumes: Task 4's endpoints and shapes; Task 2's `/article-rules`.
- `MigrosImport({ file, onImported, onCancel })`: first preview with `ai=1`, then every change re-posts the preview
  with `choices` (as `ImportTransactions` does with `changes`); a row per receipt (checkbox `aria-label`
  "Import receipt <date> <store>", total, payment select or account select, status text), opened with a
  `<details>` to its lines (category select and tag chips per article, source label); summary line with the AI
  state and "<n> new rules"; Import button; result message.
- Usable at phone width (no horizontal scroll at 390 px), like the existing import.
- `ArticleRules`: list with search field (`aria-label` "Search article rules"), edit (category, tags), delete.

- [ ] **Step 1: Write the failing e2e test** `the Migros export is imported onto its payment` (fake AI): a parent
  with a bank account and a bank booking imported from a bank CSV (as `bank-import.spec.ts`) of −7.40; upload an
  invented Migros file with that receipt (Brot 3.50, Zahnpasta 6.95, Karotten 3.90 / −3.90 / 1.95, CUMULUS BON 5.-
  −5.00, Bonus-Coupon 0: total 7.40) and a second receipt with no payment; preview shows the payment,
  "Zahnpasta" as Healthcare (AI); change "Brot" to Other Expense; import; the bank booking now has 4 lines (the voucher is one);
  Settings → article rules lists "Brot" and "Zahnpasta"; uploading the same file again shows both receipts
  "already imported". `errors` empty.
- [ ] **Step 2: Run, expect FAIL.**  **Step 3: Implement.**
- [ ] **Step 4: Run** `npm run lint && npm run type-check && npm run build` and the full e2e suite → pass.
- [ ] **Step 5: Commit** `feat(migros): import screen and article rules in Settings`; also add a note to
  `tools/converters/README.md` that the app reads the Migros export directly (as for `bank.py`) and list the spec
  in `e2e/README.md`.
