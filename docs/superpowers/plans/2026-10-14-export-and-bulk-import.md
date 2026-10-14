# Export for analysis and bulk import — Implementation Plan

> Executed inline (superpowers:executing-plans), no subagents, as the user asked. Steps use checkboxes.

**Goal:** A ZIP export for analysis and a checked, all-or-nothing bulk import of transactions from CSV/JSON.

**Architecture:** Two new backend modules with their own routers: `export_api.py` (builds the ZIP
in memory with `csv` + `zipfile`) and `import_api.py` (parses a file into rows, resolves names to IDs
with the existing validation helpers from `api.py`, reports per-row errors and duplicates, books in one
DB transaction). The frontend's `DataManager.tsx` gets the new export button and an import section
with a preview table.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, pytest; React 19 + TS + Tailwind 4.

**Spec:** `docs/superpowers/specs/2026-10-14-export-and-bulk-import-design.md`

## Global Constraints

- Backend style: black (line length 120), flake8 `--max-line-length=120 --extend-ignore=E203,W503`.
- Tests run with `pytest` from the repo root (`tests/`), helpers in `tests/helpers.py`.
- No new Python or npm dependencies (stdlib `csv`, `zipfile`, `json`; `python-multipart` is present).
- Export files: UTF-8 without BOM, `,`, `.` decimals, timestamps `YYYY-MM-DDTHH:MM:SSZ`, dates `YYYY-MM-DD`.
- Import limits: 1 MB, 1000 rows; texts ≤ 200 characters; date-only → 12:00 UTC.

## Review Focus

1. Two writable accounts with the same name (own vs. shared) — own wins, else error asking for `owner`.
2. CSV written by Swiss tools: `;` separator, BOM, header in other case, trailing empty lines.
3. An import where one row fails must store nothing (balances unchanged).
4. VIEW-shared account appears in the export but is rejected as an import target.
5. Re-importing the same file: every row is a duplicate (by reference, or by account/day/amount/category).

---

### Task 1: `reference` on transactions

**Files:** `backend/app/models.py`, `migrate.py`, `schemas.py`, `crud.py`; Test: `tests/test_import.py`

**Produces:** `models.Transaction.reference` (String, nullable); `TransactionBase.reference: Optional[str]`
(max 200); `crud.create_transaction(..., commit=True)` — with `commit=False` it only flushes.

- [ ] Test: POST /transactions with `reference="r1"` returns it; migration adds the column to a DB created
      without it (create table via raw SQL without the column, run `add_missing_columns`, inspect).
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat(transactions): optional reference for imported rows`.

### Task 2: Export for analysis

**Files:** Create `backend/app/export_api.py`, `backend/app/export_readme.md`; modify `main.py`;
Test: `tests/test_export.py`

**Consumes:** `privacy.access_level`, `privacy.can_list_user`, `common_api.visible_owner`, `asset_out`,
`planned_cost_out`, `shared_transactions`, `finance.split_amount`.
**Produces:** `GET /api/v1/export/analysis.zip`.

Columns exactly as in the spec's table. Helpers: `iso_ts(dt)` → `...Z`, `rows_to_csv(header, rows)`.

- [ ] Tests: (a) ZIP has the 11 files, headers match the spec; (b) parent sees own + VIEW-shared accounts and
      transactions, not NONE; (c) child user: own data, common files only headers; (d) a child with privacy
      is absent from members/accounts for a parent; (e) shared expense → one share row per parent with
      percent and amount; settlement row; transfer category type `TRANSFER`; (f) investment computed columns
      (follow_up_costs, total_cost); (g) README mentions user name and export date.
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat(export): ZIP of CSV files with a README for analysis`.

### Task 3: Import — parse and preview

**Files:** Create `backend/app/import_api.py`; modify `main.py`; Test: `tests/test_import.py`

**Produces:**
- `parse_file(filename: str, content: bytes) -> list[dict[str, str]]` with `"_line"`; raises `HTTPException(400)`
  for size/rows/format.
- `check_rows(db, user, raw_rows) -> list[dict]` rows with `status`, `errors`, `duplicate_of`, and resolved
  `_values` (TransactionCreate kwargs + split_shares + category).
- `POST /api/v1/import/preview` (multipart `file`).

Resolution: writable accounts = accounts whose owner has a write level (`privacy.access_level` + `can_write`).
Validation reuses `api.check_member_tag`, `api.check_shared`, `api.check_asset` (catch `HTTPException`,
take `.detail` as the row error).

- [ ] Tests: CSV `,`; CSV `;` with BOM and upper-case header; JSON; each error (missing field, bad date,
      amount ≤ 0 / not a number, unknown account/category/for/shared/item, transfer category, VIEW account,
      ambiguous account without owner, own account wins, `owner` picks the other, text too long);
      date-only → 12:00Z; duplicates by reference (existing and within file) and by account/day/amount/category;
      limits (1001 rows, > 1 MB, not CSV/JSON); preview stores nothing.
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat(import): check a CSV or JSON file and preview it`.

### Task 4: Import — book, schema, template

**Files:** `backend/app/import_api.py`; Test: `tests/test_import.py`

**Produces:** `POST /api/v1/import` (multipart `file`, form `include_duplicates` comma-separated line
numbers); `GET /api/v1/import/schema`; `GET /api/v1/import/template.csv`.

- [ ] Tests: imports ok rows, balances updated, `reference` stored; duplicates skipped unless included;
      any error → 400 and nothing stored; only-duplicates → imported 0; schema has enums of the user's
      writable accounts, non-transfer categories, dependents, splits, visible investments (child: no splits);
      template parses back through preview with only "unknown account" errors... (template uses example
      names, so check header only).
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat(import): book a checked file, JSON Schema and CSV template`.

### Task 5: Documentation

**Files:** Create `docs/import-format.md`; modify `README_DOCKER.md` (one paragraph), smoke test
`tests/smoke_test.py` (export ZIP opens; import preview of a one-row CSV).

- [ ] Write docs, extend smoke test, run it against a scratch backend. Commit `docs: import format; smoke-test export and import`.

### Task 6: Frontend

**Files:** `frontend/src/components/DataManager.tsx` (and a new `ImportTransactions.tsx` for the preview).

- [ ] Export: "Export for analysis (.zip)" (blob download via axios), "Backup (JSON)" (existing); remove CSV.
- [ ] Import transactions: template + schema download links, file picker → preview table, duplicate
      checkboxes, "Import N transactions" (disabled with errors), status message, `onImported` reloads.
- [ ] Restore backup (JSON) stays; its transactions pass `reference`.
- [ ] `npm run lint`, `npx tsc -b`, `npm run build` pass. Commit `feat(frontend): export for analysis and bulk import with preview`.

### Task 7: End-to-end check

- [ ] Puppeteer in the scratchpad: CSV with an error → blocked; fixed file with a duplicate → preview,
      import; ZIP downloaded and read with pandas (every CSV loads, transactions sum matches balances).
- [ ] Fix what it finds (test first), full `pytest`, lint, build.
