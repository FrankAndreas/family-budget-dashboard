# Bank CSV Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parents upload the Raiffeisen CSV directly in the app's import; rows land on the account carrying their
IBAN and get categories from rules (managed in Settings, with presets), then the AI, then the fallback.

**Architecture:** A bank file is turned into ordinary import rows (`bank_csv.py`) right after decoding, so the existing
preview, duplicate check, rules and booking path do the rest. Rules get whole-word, longest-first matching and a CRUD
API; presets live in `rule_presets.py`. The AI suggestion is one call in the first preview; its answers travel back as
normal `changes` marked `source: "ai"`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite; React 19 + TypeScript + react-i18next; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-23-bank-import-and-reconciliation-design.md` (Part 1 only; Part 2 gets its
own plan).

## Global Constraints

- No real IBANs, bank rows or receipts in the repo. Test IBANs: `CH93 0076 2011 6238 5295 7` and
  `CH56 0483 5012 3456 7800 9` (both already in `converter.example.toml`). Invented merchants/texts only.
- Nothing sent to the AI but cleaned booking texts and category names: no amounts, dates, IBANs, card numbers, balances.
- IBANs never written to a log line.
- Bank upload, rule management and presets are parents only.
- Every new user-visible text exists in `messages.py` (en + de) or `frontend/src/locales/{en,de}.ts`; German: Swiss
  spelling (ss, never ß), informal "du".
- Migrations keep data (this is the last time the NAS DB may be wiped, at the part 2 deploy). New migration: `0012`,
  `database_setup.HEAD = "0012"`.
- Checks before the PR: `pytest tests -q -p no:warnings`; from `backend/`: `black --check app ../tools ../tests`,
  `flake8 app ../tools --max-line-length=120 --extend-ignore=E203,W503`, `mypy app/ ../tools/ --ignore-missing-imports`;
  `cd frontend && npm run lint && npm run type-check && npm run build`; `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npm test`.

## Review Focus

1. A Raiffeisen file saved as Windows-1252 (umlauts in "Übertrag", "Bäckerei") must import, not fail with "not UTF-8"
   — pinned in Task 5 (`test_windows_1252_file`).
2. The same statement uploaded twice, or overlapping months, books nothing twice; a file converted earlier with
   `tools/converters/bank.py` and the raw file are recognised as the same rows — Task 5
   (`test_reference_matches_converter`, `test_overlap_is_duplicate`).
3. The preview is refreshed after every category change; the AI must be asked only on the first call, and an AI
   failure or the hourly limit must leave a working preview — Task 6 (`test_ai_only_when_asked`,
   `test_ai_failure_keeps_fallback`, `test_ai_limit_keeps_fallback`).
4. A child or a parent with only VIEW access must not book into an account by its IBAN — Task 5
   (`test_child_cannot_upload_bank_file`, `test_iban_of_unwritable_account`).
5. Short rule texts (`CSS`, `SALT`, `C&A`) must not match inside other words, and `DOSENBACH SPORT` must beat
   `DOSENBACH` — Task 2 (`test_whole_words`, `test_longest_wins`).

---

### Task 1: IBAN on accounts

**Files:**
- Create: `backend/app/ibans.py`, `backend/app/migrations/versions/0012_bank_import.py`
- Modify: `backend/app/models.py` (Account, ImportRule), `backend/app/schemas.py` (AccountBase/AccountUpdate/Account),
  `backend/app/crud.py` (`create_account`, `update_account`), `backend/app/api.py` (account routes),
  `backend/app/database_setup.py` (`HEAD = "0012"`), `backend/app/messages.py`, `backend/app/export_api.py`
  (accounts.csv gets an `iban` column after `type`), `backend/app/export_readme.md`
- Test: `tests/test_account_iban.py`

**Interfaces:**
- Produces: `ibans.compact(value: str) -> str` (spaces removed, uppercase); `ibans.is_valid(value: str) -> bool`
  (compact form: `^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$` and ISO 13616 mod-97 == 1); `ibans.grouped(value: str) -> str`
  (groups of four). `models.Account.iban: Optional[str]` (unique). `models.ImportRule.receipt_expected: bool`
  (default False, not null). API `Account` has `iban: Optional[str]` (compact).
- Migration 0012: `accounts.iban` String nullable + unique index `ix_accounts_iban`; `import_rules.receipt_expected`
  Boolean not null server_default `0`. Both via `op.batch_alter_table` like 0010.

- [ ] **Step 1: Write the failing tests** in `tests/test_account_iban.py`

```python
def test_parent_sets_iban(client):  # POST /accounts with "iban": "ch93 0076 2011 6238 5295 7" → 200, iban "CH9300762011623852957"
def test_update_iban_and_clear(client):  # PUT with iban → stored compact; PUT with "iban": "" → None
def test_invalid_iban(client):  # "CH93 0076 2011 6238 5295 8" (checksum) and "CH93" → 400 "That is not a valid IBAN"
def test_iban_unique(client):  # second account with same IBAN (other spacing) → 400 "Another account already has this IBAN"
def test_child_cannot_set_iban(client):  # child with own allowance: POST/PUT with iban → 403 "Only parents can set an IBAN"; without iban still 200
def test_export_has_iban(client):  # accounts.csv header contains "iban" and the compact value
def test_migration_0012(tmp_path):  # upgrade an 0011 database: column exists, existing account iban None, existing rule receipt_expected False
```

The migration test follows the pattern of the existing migration tests in `tests/test_database.py`.

- [ ] **Step 2: Run** `pytest tests/test_account_iban.py -q -p no:warnings` — Expected: FAIL (no `iban` field).
- [ ] **Step 3: Implement** `ibans.py`, model fields, migration, schemas (`iban: Optional[str] = None` on AccountBase
  and AccountUpdate), and the checks in `crud.create_account`/`crud.update_account` (empty string → None; invalid →
  `messages.api_error(400, "iban_invalid")`; taken by another account → 400 `"iban_taken"`). The route checks
  `"iban" in` the payload and the user is a child → 403 `"only_parents_set_iban"`. Messages (en/de):
  `iban_invalid` "That is not a valid IBAN" / "Das ist keine gültige IBAN"; `iban_taken` "Another account already has
  this IBAN" / "Ein anderes Konto hat diese IBAN schon"; `only_parents_set_iban` "Only parents can set an IBAN" /
  "Nur Eltern können eine IBAN eintragen". Export README: one line on the `iban` column.
  Plan call: the API returns `iban` to whoever can see the account; "children never see the field" is met in the UI
  (Task 7 shows it to parents only). A child sees only their own accounts, whose IBAN is theirs anyway.
- [ ] **Step 4: Run** the test file, then the full suite — Expected: PASS (export tests adjusted only if they pin
  the exact accounts.csv header).
- [ ] **Step 5: Commit** `feat: accounts can carry an IBAN (bank import)`

### Task 2: Whole-word, longest-first rule matching

**Files:**
- Modify: `backend/app/import_rules.py` (`adjust`, new `find`)
- Test: `tests/test_import_rules.py`

**Interfaces:**
- Produces: `import_rules.find(rules: list[models.ImportRule], description: str, kind) -> Optional[models.ImportRule]`
  — the matching rule whose category fits `kind`, longest `text` first, equal length → older (`load` order). A rule
  matches when its text occurs ignoring case with no letter or digit directly before or after it:
  `re.compile(r"(?<![^\W_])" + re.escape(text.strip()) + r"(?![^\W_])", re.IGNORECASE)`.
  `adjust` uses `find` instead of the substring loop.

- [ ] **Step 1: Write the failing tests**

```python
def test_whole_words(...):  # rule "CSS" → Healthcare: "LSV CSS Versicherung" matches; "ACCSSO Shop" doesn't (stays Unsorted)
def test_separators(...):  # "BIKE-IMPORT" matches "Einkauf bike-import.ch"; "H&M" matches "H&M Stans"; "S.OLIVER" matches "s.Oliver Kriens"
def test_longest_wins(...):  # rules "DOSENBACH" → Clothing (older) and "DOSENBACH SPORT" → Sport-like category: "Dosenbach Sport Stans" gets the latter, "Dosenbach Stans" the former
def test_equal_length_older_wins(...):
```

Write them through the existing import preview like the other tests in this file (CSV with category Unsorted).
Until Task 4 creates "Sport", use any second expense category (e.g. Entertainment).

- [ ] **Step 2: Run** `pytest tests/test_import_rules.py -q -p no:warnings` — Expected: the new tests FAIL
  (`ACCSSO` matches, oldest wins).
- [ ] **Step 3: Implement** `find` and use it in `adjust`.
- [ ] **Step 4: Run** the file, then the full suite — Expected: PASS. An existing test relying on substring matching
  inside a word is a ruling to ledger, not a silent change.
- [ ] **Step 5: Commit** `feat: import rules match whole words, the longest text wins`

### Task 3: Rules managed in Settings (API)

**Files:**
- Modify: `backend/app/import_rules.py` (routes, `rule_out`), `backend/app/messages.py`
- Test: `tests/test_import_rules.py`

**Interfaces:**
- Consumes: `models.ImportRule.receipt_expected` (Task 1).
- Produces:
  - `rule_out` adds `"category_id": str`, `"receipt_expected": bool` (keeps id, text, category, category_type, toml).
  - `POST /import/rules` body `{"text": str, "category_id": str, "receipt_expected": bool = false}` → rule_out.
  - `PUT /import/rules/{id}` same body, all fields optional → rule_out.
  - Checks (both): parents only (`require_parent`); text stripped, 2–120 chars (`remember_problem` → 400 with its
    text); text unique ignoring case among other rules → 400 `"rule_exists"` "There is already a rule for this text" /
    "Für diesen Text gibt es schon eine Regel"; category exists → else 404 `category_not_found`; category is INCOME or
    EXPENSE, or the Transfer system category (`seed.TRANSFER`); Settle up and others → 400 `"rule_category_invalid"`
    "Rules can only set income, expense or Transfer categories" / "Regeln setzen nur Einnahmen-, Ausgaben- oder
    Transfer-Kategorien".
  - `remember()` keeps an existing rule's `receipt_expected`.

- [ ] **Step 1: Write the failing tests**

```python
def test_create_list_update_delete_rule(client):  # POST → GET lists it with category_id and receipt_expected; PUT text/category/flag; DELETE
def test_rule_text_unique_ignoring_case(client):  # "Coop" then "COOP" → 400 "There is already a rule for this text"; PUT of another rule to that text → 400
def test_rule_text_length(client):  # "a" and 121 chars → 400
def test_rule_categories(client):  # Transfer allowed; Settle up → 400; unknown id → 404
def test_rules_parents_only(client):  # child: POST/PUT → 403
def test_remember_keeps_receipt_expected(client):  # flag set by PUT survives a "remember" of the same text in an import
```

- [ ] **Step 2: Run** — Expected: FAIL (405 on POST).
- [ ] **Step 3: Implement** the routes and `rule_out` fields; schemas as small Pydantic models in `import_rules.py`
  (`RuleIn`, `RuleUpdate`) following the file's style.
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: import rules can be added and edited, with "receipt expected"`

### Task 4: New default categories and rule presets

**Files:**
- Create: `backend/app/rule_presets.py`
- Modify: `backend/app/i18n.py` (`DEFAULT_NAMES`), `backend/app/seed.py` (`DEFAULT_CATEGORIES`), `backend/app/main.py`
  (where it calls `seed_categories`), `backend/app/import_rules.py` (route)
- Test: `tests/test_rule_presets.py`

**Interfaces:**
- Produces:
  - `i18n.DEFAULT_NAMES["SPORT"] = {"en": "Sport", "de": "Sport"}`, `["COMMUNICATION"] = {"en": "Communication",
    "de": "Kommunikation"}`; both EXPENSE in `DEFAULT_CATEGORIES` with `default_key`, icons 🏅 and 📡.
  - `rule_presets.PRESETS: list[tuple[str, str]]` — (text, default_key), exactly the spec's table plus
    `GARAGE WINDLING`: GROCERIES: COOP, DENNER, ALDI, LIDL, MIGROS, VOLG; TRANSPORTATION: SBB, TAMOIL, AVIA, SOCAR,
    MIGROL, GARAGE BUCHER, GARAGE WINDLIN, GARAGE WINDLING; COMMUNICATION: SWISSCOM, SUNRISE, SALT, WINGO, YALLO,
    SERAFE; HEALTHCARE: HELSANA, CSS, SWICA, SANITAS, CONCORDIA, APOTHEKE; CLOTHING: ESPRIT, WE FASHION,
    JACK & JONES, CELINE, H&M, C&A, ZALANDO, S.OLIVER, TOM TAILOR, MARC O'POLO, STREET ONE, CECIL, CHICOREE, BONITA,
    MODEVA, NEW YORKER, ANOUK, CALIDA, BLACKOUT, BELLA DONNA, ULLA POPKEN, WORLD OF JEANS, DOSENBACH, OCHSNER SHOES;
    SPORT: OCHSNER SPORT, DECATHLON, DOSENBACH SPORT, WERUN, INTERSPORT, SPORT XX, BIKE-IMPORT, PROPAIN, ROSE BIKES,
    VELO LUSSI.
  - `rule_presets.add(db: Session) -> dict` → `{"rules": int, "categories": int}`: ensures SPORT and COMMUNICATION
    (a category with that `default_key`; else one whose name is the English or German default name, which gets the
    key if it has none; else a new one in the default language's name); then adds every preset whose text isn't a rule
    yet (ignoring case) and whose category (by `default_key`) exists — presets for a deleted or renamed default are
    skipped. Commits.
  - `main.py`: `if seed_categories(db) == len(DEFAULT_CATEGORIES): rule_presets.add(db)` — only a brand-new database
    gets presets. The test `fresh_db` fixture calls `seed_categories` only, so other tests start without rules.
  - `POST /import/rules/presets` (parents) → the dict from `add`.

- [ ] **Step 1: Write the failing tests**

```python
def test_presets_button(client):  # POST /import/rules/presets → {"rules": len(PRESETS), "categories": 2}; again → {"rules": 0, "categories": 0}
def test_presets_skip_existing_text(client):  # a rule "coop" exists → it keeps its category, the preset isn't added
def test_presets_reuse_category_by_name(client):  # a category "Sport" without key exists → reused (no second "Sport"), gets default_key
def test_presets_skip_missing_default(client):  # Clothing deleted → no CLOTHING presets, the rest added
def test_presets_parents_only(client):
def test_new_database_gets_presets(tmp_path):  # the app's startup seeding on an empty DB creates the rules; a second startup adds none
def test_new_categories_in_both_languages(client):  # German request shows "Kommunikation"
def test_presets_categorise_bank_texts(client):  # after presets: import CSV rows "Einkauf TWINT Dosenbach Sport Stans" → Sport, "LSV CSS Versicherung" → Healthcare
```

- [ ] **Step 2: Run** `pytest tests/test_rule_presets.py -q -p no:warnings` — Expected: FAIL (no module).
- [ ] **Step 3: Implement.** `test_default_category_names.py`/`test_categories.py` may pin the default list; extend
  their expectations with the two new categories.
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: rule presets for Swiss shops, categories Sport and Communication`

### Task 5: Reading the bank file in the import

**Files:**
- Create: `backend/app/bank_csv.py`
- Modify: `backend/app/import_api.py` (`parse_file`, `check_file`, `public`, preview route), `backend/app/messages.py`,
  `tools/converters/README.md` (direct upload first; the converter as the alternative)
- Test: `tests/test_bank_import.py`

**Interfaces:**
- Consumes: `ibans.compact` (Task 1), `import_rules.find` (Task 2).
- Produces:
  - `bank_csv.decode(content: bytes) -> str`: UTF-8 with or without BOM; on `UnicodeDecodeError`, Windows-1252 only
    if the result `is_bank`, else the existing `file_not_utf8` error.
  - `bank_csv.is_bank(text: str) -> bool`: first line split on `;`, names stripped and casefolded, contains `iban`,
    `booked at`, `text`, `credit/debit amount`.
  - `bank_csv.clean(text: str) -> tuple[str, Optional[tuple[date, time]]]`: (description, purchase date+time of a
    card line) — the converter's `CARD`, `CARD_NUMBER`, `IBAN`, `SPACES` regexes and logic copied (the converter
    keeps its own copy, untouched).
  - `bank_csv.rows(text: str) -> list[dict]`: one raw import row per non-empty line, in the shape of
    `import_api.parse_csv` rows (`_line` + every name in `FIELDS`) plus `_iban` (compact), `_balance`
    (Optional[float]), `_skip` (True when amount is 0). Fields: `date` = `common`-style: card line → ISO with
    Europe/Zurich offset (`datetime.combine(day, at, tzinfo=ZoneInfo("Europe/Zurich")).isoformat()`), else the
    `Booked At` date `YYYY-MM-DD`; `amount` = absolute value as text; `category` = `"Unsorted"` for money out,
    `"Other Income"` for money in (the seed's English names, which `Lookups.categories` knows); `description` =
    cleaned text cut to `import_api.MAX_TEXT`; `reference` = `"bank:" + sha256("|".join([iban, booked at, text,
    credit/debit amount, balance]))[:16]` over the **raw** column values, exactly as `tools/converters/bank.py`.
    A row whose amount or date can't be read keeps the raw value so `check_row` reports it.
  - In `import_api`: `parse_file` uses `bank_csv.decode`, and for a bank file returns `bank_csv.rows`; a parsed file
    is returned as `(rows, is_bank)` — change `parse_file`'s return to `tuple[list[dict], bool]` and its one caller.
  - In `check_file` for a bank file: `require_parent` with the new key `only_parents_import_bank` "Only parents can
    import bank statements" / "Nur Eltern können Kontoauszüge importieren" (403); each row's `account`/`owner` are
    filled from the writable account (`Lookups.writable`) whose `iban` equals `_iban`; none → the row gets the error
    `no_account_for_iban` "No account has the IBAN {iban} (add it to the account in Settings)" / "Kein Konto hat die
    IBAN {iban} (trag sie beim Konto in den Einstellungen ein)", with `{iban}` grouped; `_skip` rows get status
    `"skipped"` with note `bank_zero_amount` "Amount 0, not booked" / "Betrag 0, wird nicht gebucht" and are never
    booked. Each row's `source` is `"rule"`, `"ai"`, `"change"` or `"fallback"` (non-bank files: `None`).
  - `public()` counts `"skipped"` and, for a bank file, adds `"balances": [{"account_id", "account", "file_balance",
    "app_balance"}]`: per account in the file, the `_balance` of its latest line (by date, then line) and the
    account's current balance plus the signed amounts of this preview's `ok` rows on it.

- [ ] **Step 1: Write the failing tests** (invented rows; header
  `IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date`)

```python
def test_bank_rows_go_to_account_by_iban(client):  # two accounts with the two test IBANs; one file with lines for both → each row's account right, amounts signed (−2.0 out, 100 in)
def test_card_line_uses_purchase_date_and_merchant(client):  # "Einkauf Bäckerei Muster 06.09.2026, 08:45, Debit Mastercard-Nr. 123456xxxxxx1234" → description "Bäckerei Muster", date 2026-09-06 08:45 Zurich
def test_text_loses_iban_and_card_number(client):
def test_unknown_iban_is_an_error(client):  # error text contains "CH56 0483 5012 3456 7800 9"; import refused
def test_iban_of_unwritable_account(client):  # other parent's account shared VIEW → same error
def test_child_cannot_upload_bank_file(client):  # 403 "Only parents can import bank statements"
def test_zero_amount_skipped(client):
def test_windows_1252_file(client):  # "Übertrag" encoded cp1252 → imports; a non-bank cp1252 file still "not UTF-8"
def test_reference_matches_converter(client):  # bank_csv.rows reference == tools.converters.bank convert() reference for the same line
def test_overlap_is_duplicate(client):  # import, then upload the same file plus one new line → 1 ok, rest duplicate
def test_rules_and_fallback(client):  # rule "MUSTER" → Groceries: source "rule"; other out-line Unsorted "fallback"; in-line Other Income
def test_transfer_rule(client):  # rule "Übertrag" → Transfer: out-line booked as transfer out
def test_balance_check(client):  # balances: file_balance = latest line's Balance, app_balance = 0 + sum of ok rows
def test_normal_csv_unchanged(client):  # the template CSV still previews as before (source None, no balances)
```

- [ ] **Step 2: Run** `pytest tests/test_bank_import.py -q -p no:warnings` — Expected: FAIL (bank header read as
  a normal CSV: "account required").
- [ ] **Step 3: Implement** as in Interfaces; IBANs only in the error text, never `logger`.
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: the Raiffeisen CSV is imported directly in the app`

### Task 6: AI suggestions for bank rows

**Files:**
- Modify: `backend/app/receipt_ai.py`, `backend/app/import_api.py` (preview route), `backend/app/messages.py`
- Test: `tests/test_bank_ai.py`

**Interfaces:**
- Consumes: Task 5's rows with `source`.
- Produces:
  - `receipt_ai.MAX_TEXTS = 200`; `receipt_ai.TEXT_PROMPTS` (de/en) and `text_prompt(expense: list[str], income:
    list[str], texts_out: list[str], texts_in: list[str], lang: str) -> str`: asks for JSON only,
    `{"<text>": "<category>"}`, each money-out text one of the expense names, each money-in text one of the income
    names; the texts are given as JSON lists. Only expense/income categories, never Transfer/Settle up/Unknown expense.
  - `receipt_ai.parse_texts(answer: str, allowed_out: dict[str, str], allowed_in: dict[str, str], texts_out,
    texts_in) -> dict[str, str]` → `{text: category name in the person's language}`; names matched ignoring case via
    `i18n.all_names`; unknown or wrong-kind names dropped; JSON inside a ```json fence accepted like `parse`.
  - `receipt_ai.suggest(db, user, texts_out: list[str], texts_in: list[str]) -> tuple[dict[str, str], str,
    Optional[str]]` → (suggestions, status, message). Status `"off"` (AI not set up; no read counted), `"ok"`,
    `"capped"` (more than 200 distinct texts: first 200 asked; message `bank_ai_capped` "The AI looked at the first
    {count} texts; the rest stay unsorted" / "Die KI hat die ersten {count} Texte angeschaut, der Rest bleibt
    unsortiert"), `"limit"` (take_read's 429; message its detail), `"failed"` (AiUnavailable or unreadable answer;
    message `bank_ai_failed` "The AI couldn't suggest categories this time" / "Die KI konnte diesmal keine Kategorien
    vorschlagen"). Counts one read via `take_read` before calling.
  - `FakeClient.complete`: when the prompt is a text prompt (detect by a marker string in `TEXT_PROMPTS`), answer
    every money-out text with `"Groceries"` and every money-in text with `"Salary"`; else the fixed receipt as today.
  - Preview route: new form field `ai: str = Form("")`. When `ai == "1"` and the file is a bank file: after
    `check_file`, collect the distinct descriptions of rows with `source == "fallback"` and status not `"error"`,
    split by sign; `suggest`; add `{line: {"category": name, "source": "ai"}}` for each such row with a suggestion
    to the changes and run `check_file` again (`file.file.seek(0)`). Response adds `"ai": {"status", "message",
    "suggestions": {line: {"category", "source": "ai"}}}`. Without `ai == "1"` no AI call and no `"ai"` key.
  - `check_file`: a change with `"source": "ai"` gives the row `source "ai"` (instead of `"change"`).

- [ ] **Step 1: Write the failing tests** (the `ai` fixture pattern from `tests/test_receipt_ai.py`)

```python
def test_ai_suggests_for_fallback_rows_only(client, ai):  # one rule row, two fallback rows (same text twice + another) → fake answer {..}; suggestions only for fallback lines; sent prompt contains each distinct text once
def test_only_texts_are_sent(client, ai):  # sent content contains no IBAN, no amount ("84.30"), no balance, no date
def test_ai_only_when_asked(client, ai):  # preview without ai=1 → fake.sent == [] and no "ai" key
def test_ai_off(client, monkeypatch):  # no token → status "off", no read counted
def test_ai_failure_keeps_fallback(client, ai):  # fake raises AiUnavailable / answers "nonsense" → status "failed", rows stay Unsorted, 200
def test_ai_limit_keeps_fallback(client, ai, monkeypatch):  # RECEIPT_AI_READS_PER_HOUR=1, two previews with ai=1 → second status "limit", 200
def test_unknown_or_wrong_kind_names_dropped(client, ai):  # answer gives "Salary" for a money-out text, "Nonsense" for another → no suggestion for either
def test_ai_never_suggests_transfer(client, ai):  # answer "Transfer" → dropped; prompt lists no Transfer/Settle up
def test_capped(client, ai, monkeypatch):  # monkeypatch MAX_TEXTS=2, three distinct texts → status "capped", two asked
def test_ai_suggestion_books_and_can_be_remembered(client, ai):  # import with the returned suggestions as changes (+ remember on one) → booked with those categories; rule saved
```

- [ ] **Step 2: Run** `pytest tests/test_bank_ai.py -q -p no:warnings` — Expected: FAIL (no `ai` key).
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run** the file, `tests/test_receipt_ai.py`, and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: the AI suggests categories for bank rows no rule knows`

### Task 7: Frontend and browser test

**Files:**
- Modify: `frontend/src/accounts.ts` (Account type: `iban?: string | null`), `frontend/src/components/AccountCards.tsx`
  (IBAN field in add and edit forms, parents only; shown grouped on the card for parents),
  `frontend/src/components/ImportRules.tsx` (manager), `frontend/src/components/ImportTransactions.tsx`,
  `frontend/src/locales/en.ts`, `frontend/src/locales/de.ts`
- Create: `e2e/tests/bank-import.spec.ts`

**Interfaces:**
- Consumes: Task 1 account `iban`; Task 3 rule API; Task 4 `POST /import/rules/presets`; Tasks 5–6 preview fields
  `source`, `status "skipped"`, `balances`, `ai`.
- Produces (UI):
  - Account forms: optional "IBAN" input; API error shown as today.
  - ImportRules: list (text, category, "receipt expected" ✓), add form (text, category select of income/expense
    categories plus Transfer, checkbox "receipt expected"), edit inline, delete, TOML copy kept, button
    "Add suggested rules" → message "{rules} rules and {categories} categories added" (plural forms).
  - ImportTransactions: `Change` gets `source?: 'ai'`, sent in `changes`. The first preview of a file sends `ai=1`;
    the returned `ai.suggestions` go into `changes` (not marked "remember"); later previews and the import send them
    back. Row note: "by rule {rule}" (as today), "AI suggestion", or "unsorted" for fallback; skipped rows greyed
    with their note; `ai.message` shown above the table when present; a balance box per account: "Bank: CHF x · App
    after import: CHF y", highlighted when they differ. The import's help text says the Raiffeisen CSV can be
    uploaded as it is, once the accounts carry their IBAN.

- [ ] **Step 1: Write the failing browser test** `e2e/tests/bank-import.spec.ts` (helpers from `e2e/tests/helpers.ts`;
  fake AI is on in `playwright.config.ts`):

```ts
test('bank statement upload', ...)
// parent sets IBAN CH93 0076 2011 6238 5295 7 on an account in the account form
// Settings → Data Management: "Add suggested rules" → message with the count; rule list shows "DOSENBACH SPORT"
// add rule "MUSTER AG" → Salary
// import a generated CSV (written in the test) with lines: "Einkauf TWINT Coop Stans" −20.00, "Gutschrift MUSTER AG" 5000,
//   "Einkauf Kiosk Beispiel" −3.50, one line with amount 0
// preview: Coop row "by rule COOP" → Groceries; Muster row by rule → Salary; Kiosk row "AI suggestion" → Groceries; zero row skipped;
//   balance box shows the file's balance
// import → account balance changes by 4976.50
```

- [ ] **Step 2: Run** `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npx playwright test bank-import` — Expected: FAIL
  (no IBAN field).
- [ ] **Step 3: Implement** the three components and texts (en + de, every key in both; `npm run lint` runs the text
  check).
- [ ] **Step 4: Run** the browser test, then all checks from Global Constraints — Expected: all PASS, 15 browser tests.
- [ ] **Step 5: Commit** `feat: bank upload, IBAN and rule manager in the app`
