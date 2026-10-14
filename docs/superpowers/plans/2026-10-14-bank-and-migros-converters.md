# Bank and Migros converters — Implementation Plan

> Executed inline (superpowers:executing-plans), no subagents, as the user asked. Steps use checkboxes.

**Goal:** Transfers in the import, plus two stdlib converters that turn bank and Migros exports into the import format.

**Architecture:** The app change sits in `seed.py`, `import_api.py` and `api.py` (Transfer vs. Settle up told apart by
name). The converters live in `tools/converters/`: `common.py` (reading CSVs, config + schema checks, writing the
import CSV, Zurich dates), `bank.py` and `migros.py`, each with a `convert(...)` function for tests and a `main()` CLI.

**Tech Stack:** FastAPI, SQLAlchemy, pytest; Python 3.11+ stdlib (`tomllib`, `zoneinfo`); React 19 + TS.

**Spec:** `docs/superpowers/specs/2026-10-14-bank-and-migros-converters-design.md`

## Global Constraints

- black (line length 120) and flake8 `--max-line-length=120 --extend-ignore=E203,W503` for `backend/app` and `tools/`.
- No new dependencies. No real IBANs, names or bookings in tests, docs or examples (use CH9300762011623852957 etc.).
- Import field `direction` is `in` / `out`, required for Transfer rows only.
- Converter output: `,`-separated UTF-8 CSV with the import header plus `owner` and `direction`; amounts positive, 2 decimals.

## Review Focus

1. A Transfer row with `for`/`shared`/`item` → error; Settle up still rejected in import, update and delete.
2. Card purchase at midnight (`06.09.2026, 00:15`) → date written with the right Zurich offset (summer/winter).
3. Two identical purchases on the same day → distinct references (balance differs).
4. A config naming a category the schema lacks, or an expense category on a credit-only rule → stops, writes nothing.
5. Migros receipt whose category sum is negative or 0 → refund category or skipped.

---

### Task 1: Transfer category in the app

**Files:** `backend/app/seed.py`, `import_api.py`, `api.py`; Test: `tests/test_import.py`, `tests/test_transfers.py`

**Produces:** seeded `Transfer` (TRANSFER), `Unsorted` (EXPENSE), `Reimbursements` (INCOME); import field
`direction`; schema `direction` + `x-category-types`; `DELETE` allowed and `PUT` limited (description, date) for
Transfer; Settle up unchanged.

- [ ] Tests: import Transfer in/out (balances ±), without direction, with bad direction, direction on Groceries,
      Transfer with for/item → errors; Settle up row still rejected; schema has Transfer, `direction`, types;
      delete a Transfer (balance restored); PUT description ok, PUT amount/category → 400; Settle up delete/PUT → 400;
      seed adds the three categories to a DB that lacks them.
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat(import): transfers between own accounts`.

### Task 2: Frontend and docs for transfers

**Files:** `frontend/src/pages/dashboard/Dashboard.tsx`, `frontend/src/components/ImportTransactions.tsx`,
`docs/import-format.md`.

- [ ] Delete button for Transfer transactions (not Settle up), edit stays hidden for all transfers.
- [ ] Preview shows `direction` next to the amount for Transfer rows.
- [ ] Docs: `direction` field, transfers paragraph. Lint, type-check, build. Commit `feat(frontend): delete imported transfers; docs`.

### Task 3: Converter common parts and bank converter

**Files:** Create `tools/converters/{__init__,common,bank}.py`, `tools/converters/converter.example.toml`;
Test: `tests/test_converters.py`

**Produces:** `common.read_rows(path, required) -> list[dict]` (lower-case keys, `_line`), `common.Schema(path)`
(`accounts`, `owners`, `categories: dict[name, type]`, `items`, `children`, `splits`), `common.ConfigError(problems)`,
`common.zurich(date, time) -> str`, `common.write_import(path, rows)`; `bank.convert(rows, config, schema) -> Result`
(`rows`, `unrecognised`, `ignored`, `transfers`, `booked`, `balance`).

- [ ] Tests (invented export): each text kind; card date/time from text with offset; card number removed; first
      match wins; `sign`; fallback + unrecognised; reference stable/distinct; unknown IBAN stops; config checks
      (unknown category/item/account, bad regex, wrong type for sign, rule without category); Windows-1252 file;
      balance = latest booking; CLI writes `<name>-import.csv` that the app's preview accepts.
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat(tools): bank export converter`.

### Task 4: Migros converter

**Files:** Create `tools/converters/migros.py`; Test: `tests/test_converters.py`

- [ ] Tests: grouping by receipt; article rule over branch over default; `for`; negative sum → refund category;
      0 → skipped; reference; date+time offset; totals per day; config checks.
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat(tools): Migros receipt converter`.

### Task 5: Docs, CI, end to end

- [ ] `tools/converters/README.md` (usage, config reference); link from `docs/import-format.md`; CI lints `tools/`.
- [ ] End to end against a scratch backend: invented bank + Migros exports → converters → preview → import;
      bank balance as reported, Migros account 0. Full pytest, lint, build. Commit `docs(tools): converter guide`.
