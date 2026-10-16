# Import categories and rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change a row's category in the import preview, remember it as an app rule, apply app rules to fallback
rows, manage rules in Settings, and hand them to `bank.py` through the JSON Schema (issue #16).

**Architecture:** New model `ImportRule` and module `backend/app/import_rules.py` (matching, changes, TOML block,
rules router). `import_api.check_file` applies changes and rules to each raw row before `check_row`;
`run_import` saves remembered rules in the same transaction. The schema gets `x-rules`; `tools/converters`
reads and applies them. Frontend: dropdown in `ImportTransactions.tsx`, new `ImportRules.tsx` in Settings.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite; Python 3.11+ stdlib (converter); React 19, TS.

**Spec:** `docs/superpowers/specs/2026-10-16-import-categories-and-rules-design.md`

## Global Constraints

- Sign never flips: file category EXPENSE → EXPENSE or Transfer (out); INCOME → INCOME or Transfer (in).
- App rules only on rows whose file category is "Unsorted" or "Other Income" and that the user didn't change;
  oldest rule first; text contained in the description ignoring case; rule category must fit the sign.
- Rules saved only by a successful `POST /import`; only parents (`remember` from a child → 403).
- Errors: "Can't change <file category> to <new category>", "rule text: 2 to 120 characters",
  "changes must be JSON", "Only parents can save import rules".
- No real data in tests. Commits end with the Co-Authored-By / Claude-Session lines.

## Review Focus

1. A change on a row that is also a duplicate: duplicate detection must use the new category.
2. A failed import (any row error) must not save rules.
3. TOML block with quotes, backslashes and regex characters must parse with `tomllib` and match the text.
4. Rule text that is only spaces, or the same text in different case → one rule, updated.
5. The re-preview after a dropdown change must keep the user's other changes and "Import anyway" ticks.

---

### Task 1: Changes and rules in the import (backend)

**Files:** Modify `backend/app/models.py`, `backend/app/import_api.py`, `backend/app/main.py`;
Create `backend/app/import_rules.py`, `tests/test_import_rules.py`.

**Interfaces — Produces:** `models.ImportRule(id, text, category_id, created_at)`;
`import_rules.parse_changes(text: str) -> dict[int, dict]`;
`import_rules.adjust(raw: dict, change: dict | None, lookups, rules: list[models.ImportRule]) -> tuple[dict, str | None, str | None]` (row, problem, rule text);
`import_rules.load(db) -> list[models.ImportRule]`; `import_rules.remember(db, text, category)`;
`import_rules.toml_block(text: str, category: models.Category) -> str`; router with `GET /import/rules`, `DELETE /import/rules/{id}`.

- [ ] **Step 1: Tests** `tests/test_import_rules.py`:

```python
"""Import preview: change a row's category, remember it as a rule, rules applied to fallback rows (issue #16)."""

import json
import re
import tomllib

import pytest

from helpers import BASE_URL, category_id, create_account, register
from test_import import upload

HEADER = "date,account,category,amount,direction,description,reference"


def csv(*lines):
    return "\n".join([HEADER, *lines]) + "\n"


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    create_account(client, headers, "Bank")
    return headers


def send(client, headers, content, changes=None, path="import/preview", **data):
    if changes is not None:
        data["changes"] = json.dumps(changes)
    return upload(client, headers, content, path=path, **data)


def rows(client, headers, content, changes=None):
    response = send(client, headers, content, changes)
    assert response.status_code == 200, response.text
    return response.json()["rows"]


def rules(client, headers):
    return client.get(f"{BASE_URL}/import/rules", headers=headers).json()


BAKERY = "2026-09-06,Bank,Unsorted,22.10,,Bäckerei Muster,bank:1"
REFUND = "2026-09-07,Bank,Other Income,15.00,,Rückzahlung Muster,bank:2"


class TestChanges:
    def test_expense_to_expense(self, client, mum):
        [row] = rows(client, mum, csv(BAKERY), {"2": {"category": "Groceries"}})
        assert row["status"] == "ok"
        assert (row["category"], row["file_category"], row["rule"]) == ("Groceries", "Unsorted", None)

    def test_to_transfer_takes_the_direction_from_the_sign(self, client, mum):
        out, back = rows(client, mum, csv(BAKERY, REFUND), {"2": {"category": "Transfer"}, "3": {"category": "transfer"}})
        assert (out["status"], out["direction"]) == ("ok", "out")
        assert (back["status"], back["direction"]) == ("ok", "in")

    @pytest.mark.parametrize("target", ["Salary", "Settle up", "Nonsense"])
    def test_not_allowed(self, client, mum, target):
        [row] = rows(client, mum, csv(BAKERY), {"2": {"category": target}})
        assert row["status"] == "error"
        assert f"Can't change Unsorted to {target}" in row["errors"]

    def test_transfer_row_cant_change(self, client, mum):
        [row] = rows(client, mum, csv("2026-09-06,Bank,Transfer,5,out,Savings,"), {"2": {"category": "Groceries"}})
        assert "Can't change Transfer to Groceries" in row["errors"]

    def test_import_books_the_new_category(self, client, mum):
        response = send(client, mum, csv(BAKERY), {"2": {"category": "Groceries"}}, path="import")
        assert response.json() == {"imported": 1, "skipped": 0}
        booked = rows(client, mum, csv(BAKERY), {"2": {"category": "Groceries"}})
        assert booked[0]["status"] == "duplicate"  # same reference
        account = client.get(f"{BASE_URL}/accounts", headers=mum).json()[0]["id"]
        [t] = client.get(f"{BASE_URL}/accounts/{account}/transactions", headers=mum).json()
        assert t["category_id"] == category_id(client, "Groceries") and t["amount"] == -22.10

    def test_duplicate_check_uses_the_new_category(self, client, mum):
        no_ref = "2026-09-06,Bank,Unsorted,22.10,,Bäckerei Muster,"
        send(client, mum, csv(no_ref), {"2": {"category": "Groceries"}}, path="import")
        assert rows(client, mum, csv(no_ref))[0]["status"] == "ok"  # Unsorted: a different booking
        assert rows(client, mum, csv(no_ref), {"2": {"category": "Groceries"}})[0]["status"] == "duplicate"

    def test_bad_changes(self, client, mum):
        bad = upload(client, mum, csv(BAKERY), changes="{nope")
        assert bad.status_code == 400 and bad.json()["detail"] == "changes must be JSON"
        missing = send(client, mum, csv(BAKERY), {"9": {"category": "Groceries"}})
        assert missing.status_code == 400


class TestRemember:
    def test_import_saves_a_rule(self, client, mum):
        changes = {"2": {"category": "Groceries", "remember": " Bäckerei "}}
        assert send(client, mum, csv(BAKERY), changes, path="import").status_code == 200
        assert [(r["text"], r["category"]) for r in rules(client, mum)] == [("Bäckerei", "Groceries")]

    def test_preview_saves_nothing(self, client, mum):
        rows(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "Bäckerei"}})
        assert rules(client, mum) == []

    def test_same_text_updates(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "Bäckerei"}}, path="import")
        other = "2026-09-08,Bank,Unsorted,9.00,,Bäckerei Zwei,bank:3"
        send(client, mum, csv(other), {"2": {"category": "Dining Out", "remember": "BÄCKEREI"}}, path="import")
        assert [(r["text"], r["category"]) for r in rules(client, mum)] == [("Bäckerei", "Dining Out")]

    @pytest.mark.parametrize("text", ["B", "x" * 121, "   "])
    def test_text_length(self, client, mum, text):
        [row] = rows(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": text}})
        assert "rule text: 2 to 120 characters" in row["errors"]

    def test_failed_import_saves_no_rule(self, client, mum):
        broken = "2026-09-09,Nowhere,Unsorted,5,,x,"
        changes = {"2": {"category": "Groceries", "remember": "Bäckerei"}}
        assert send(client, mum, csv(BAKERY, broken), changes, path="import").status_code == 400
        assert rules(client, mum) == []

    def test_children_cant_remember(self, client, mum):
        kid = register(client, "kid", role="CHILD", by=mum)
        create_account(client, kid, "Pocket")
        line = "2026-09-06,Pocket,Unsorted,3,,Kiosk,"
        response = send(client, kid, csv(line), {"2": {"category": "Groceries", "remember": "Kiosk"}})
        assert response.status_code == 403 and response.json()["detail"] == "Only parents can save import rules"


class TestApplying:
    @pytest.fixture
    def bakery_rule(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "bäckerei"}}, path="import")

    def test_fallback_rows_get_the_rule(self, client, mum, bakery_rule):
        [row] = rows(client, mum, csv("2026-10-01,Bank,Unsorted,8,,BÄCKEREI Muster Bahnhof,bank:9"))
        assert (row["category"], row["rule"], row["file_category"]) == ("Groceries", "bäckerei", "Unsorted")

    def test_only_fallback_rows(self, client, mum, bakery_rule):
        [row] = rows(client, mum, csv("2026-10-01,Bank,Dining Out,8,,Bäckerei Café,bank:9"))
        assert (row["category"], row["rule"]) == ("Dining Out", None)

    def test_sign_must_fit(self, client, mum, bakery_rule):
        [row] = rows(client, mum, csv("2026-10-01,Bank,Other Income,8,,Bäckerei refund,bank:9"))
        assert (row["category"], row["rule"]) == ("Other Income", None)

    def test_oldest_rule_first_and_change_wins(self, client, mum, bakery_rule):
        other = "2026-09-08,Bank,Unsorted,9.00,,Muster AG,bank:3"
        send(client, mum, csv(other), {"2": {"category": "Clothing", "remember": "Muster"}}, path="import")
        line = "2026-10-01,Bank,Unsorted,8,,Bäckerei Muster,bank:9"
        assert rows(client, mum, csv(line))[0]["category"] == "Groceries"
        changed = rows(client, mum, csv(line), {"2": {"category": "Healthcare"}})[0]
        assert (changed["category"], changed["rule"]) == ("Healthcare", None)

    def test_transfer_rule(self, client, mum):
        send(client, mum, csv(REFUND), {"2": {"category": "Transfer", "remember": "Rückzahlung"}}, path="import")
        [row] = rows(client, mum, csv("2026-10-02,Bank,Other Income,20,,Rückzahlung X,bank:8"))
        assert (row["category"], row["direction"]) == ("Transfer", "in")


class TestRulesApi:
    def test_list_delete_parents_only(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "Bäckerei"}}, path="import")
        [rule] = rules(client, mum)
        assert rule["category_type"] == "EXPENSE"
        kid = register(client, "kid", role="CHILD", by=mum)
        assert client.get(f"{BASE_URL}/import/rules", headers=kid).status_code == 403
        assert client.delete(f"{BASE_URL}/import/rules/{rule['id']}", headers=kid).status_code == 403
        assert client.delete(f"{BASE_URL}/import/rules/{rule['id']}", headers=mum).status_code == 200
        assert rules(client, mum) == []

    @pytest.mark.parametrize("text", ['Café "Zum Bären"', r"C:\Shop", "Shop (Zürich) 50% #1 a.b"])
    def test_toml_block(self, client, mum, text):
        line = f'2026-09-06,Bank,Unsorted,5,,"{text.replace(chr(34), chr(34) * 2)}",'
        response = send(client, mum, csv(line), {"2": {"category": "Groceries", "remember": text}}, path="import")
        assert response.status_code == 200, response.text
        [rule] = rules(client, mum)
        parsed = tomllib.loads(rule["toml"])["bank"]["rules"][0]
        assert parsed["category"] == "Groceries"
        assert re.search(parsed["match"], f"Einkauf {text.upper()} 01.09.2026", re.IGNORECASE)

    def test_toml_block_for_a_transfer(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Transfer", "remember": "Bäckerei"}}, path="import")
        parsed = tomllib.loads(rules(client, mum)[0]["toml"])["bank"]["rules"][0]
        assert parsed == {"match": "Bäckerei", "action": "transfer"}

    def test_schema_lists_rules(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "Bäckerei"}}, path="import")
        schema = client.get(f"{BASE_URL}/import/schema", headers=mum).json()
        assert schema["x-rules"] == [{"contains": "Bäckerei", "category": "Groceries"}]
```

- [ ] **Step 2: Run** `tests/test_import_rules.py` — Expected: most fail (no `changes`, no `/import/rules`).

- [ ] **Step 3: Implement**

`models.py`:

```python
class ImportRule(Base):
    """Text in an imported row's description → category; learnt in the import preview, also used by the converter."""

    __tablename__ = "import_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Matched ignoring case, anywhere in the description
    text = Column(String)
    category_id = Column(String, ForeignKey("categories.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    category = relationship("Category")
```

`import_rules.py`:

```python
"""Import rules: text in a row's description → category. Learnt in the import preview ("remember"), applied to rows
that arrive in a fallback category, and handed to the bank converter through the JSON Schema (x-rules)."""

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import auth, database, models
from .seed import SETTLE_UP

router = APIRouter()

# The categories the bank converter uses for lines none of its rules recognise
FALLBACKS = ("unsorted", "other income")
MIN_TEXT, MAX_TEXT = 2, 120
TRANSFER = models.CategoryType.TRANSFER


def key(name: str) -> str:
    return (name or "").strip().casefold()


def require_parent(user: models.User) -> None:
    if user.role != models.UserRole.PARENT:
        raise HTTPException(status_code=403, detail="Only parents can save import rules")


def parse_changes(text: str) -> dict[int, dict]:
    """{line: {"category": name, "remember": text}} from the form field (JSON with line numbers as keys)."""
    if not text:
        return {}
    try:
        raw = json.loads(text)
        changes = {int(line): change for line, change in raw.items()}
        if not all(isinstance(c, dict) and isinstance(c.get("category"), str) for c in changes.values()):
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=400, detail="changes must be JSON")
    return changes


def load(db: Session) -> list[models.ImportRule]:
    return db.query(models.ImportRule).order_by(models.ImportRule.created_at, models.ImportRule.id).all()


def fits(category: models.Category, kind) -> bool:
    return category.type == kind or category.type == TRANSFER


def with_category(raw: dict, category: models.Category, kind) -> dict:
    row = {**raw, "category": category.name}
    if category.type == TRANSFER:
        # The sign stays: an expense row is money out, an income row money in
        row["direction"] = "out" if kind == models.CategoryType.EXPENSE else "in"
    return row


def adjust(raw: dict, change: Optional[dict], lookups, rules: list) -> tuple[dict, Optional[str], Optional[str]]:
    """The row with the user's change or a matching rule applied; plus a problem and the rule's text."""
    file_category = lookups.categories.get(key(raw["category"]))
    kind = file_category.type if file_category else None
    if change:
        target = lookups.categories.get(key(change["category"]))
        allowed = (
            kind in (models.CategoryType.INCOME, models.CategoryType.EXPENSE)
            and target is not None
            and target.name != SETTLE_UP
            and fits(target, kind)
        )
        if not allowed:
            return raw, f"Can't change {raw['category']} to {change['category']}", None
        return with_category(raw, target, kind), None, None
    if file_category and key(file_category.name) in FALLBACKS:
        description = key(raw["description"])
        for rule in rules:
            if key(rule.text) in description and fits(rule.category, kind):
                return with_category(raw, rule.category, kind), None, rule.text
    return raw, None, None


def remember_problem(text: str) -> Optional[str]:
    return None if MIN_TEXT <= len(text.strip()) <= MAX_TEXT else f"rule text: {MIN_TEXT} to {MAX_TEXT} characters"


def remember(db: Session, text: str, category: models.Category) -> None:
    """Save text → category; the same text (ignoring case) updates the existing rule. The caller commits."""
    text = text.strip()
    existing = next((r for r in load(db) if key(r.text) == key(text)), None)
    if existing:
        existing.category_id = category.id
    else:
        db.add(models.ImportRule(text=text, category_id=category.id))
    db.flush()


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def toml_block(text: str, category: models.Category) -> str:
    """The rule for converter.toml: the text as a regular expression (bank.py matches ignoring case)."""
    target = 'action = "transfer"' if category.type == TRANSFER else f"category = {toml_string(category.name)}"
    return f"[[bank.rules]]\nmatch = {toml_string(re.escape(text))}\n{target}\n"


def rule_out(rule: models.ImportRule) -> dict:
    return {
        "id": rule.id,
        "text": rule.text,
        "category": rule.category.name,
        "category_type": rule.category.type.value,
        "toml": toml_block(rule.text, rule.category),
    }


@router.get("/import/rules")
def list_rules(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    require_parent(current_user)
    return [rule_out(r) for r in load(db)]


@router.delete("/import/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    rule = db.query(models.ImportRule).filter(models.ImportRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}
```

`import_api.py`:
- `from . import import_rules`.
- `check_file(db, user, file, changes=None)`:

```python
def check_file(db: Session, user: models.User, file: UploadFile, changes: Optional[dict] = None) -> list[dict]:
    raw_rows = parse_file(file.filename or "", file.file.read(MAX_BYTES + 1))
    changes = changes or {}
    unknown = set(changes) - {raw["_line"] for raw in raw_rows}
    if unknown:
        raise HTTPException(status_code=400, detail=f"changes name line {min(unknown)}, which isn't in the file")
    if any(c.get("remember") for c in changes.values()):
        import_rules.require_parent(user)
    lookups = Lookups(db, user)
    rules = import_rules.load(db)
    seen: dict[str, int] = {}
    rows = []
    for raw in raw_rows:
        change = changes.get(raw["_line"])
        adjusted, problem, rule = import_rules.adjust(raw, change, lookups, rules)
        out = check_row(db, user, lookups, adjusted, seen)
        # Any non-empty text is checked, so "   " is an error rather than silently ignored
        remember = (change or {}).get("remember") or ""
        problems = [problem, import_rules.remember_problem(remember) if remember else None]
        for text in filter(None, problems):
            out["errors"].append(text)
            out["status"] = "error"
        out.update(file_category=raw["category"], rule=rule)
        rows.append(out)
    return rows
```

- `preview_import`: add `changes: str = Form("")`, pass `import_rules.parse_changes(changes)`.
- `run_import`: same; after creating transactions and before `db.commit()`:

```python
        for row in chosen_or_all_rows_with_remember:
            ...
```

  concretely: for every row (also skipped duplicates) whose change has a non-empty `remember`:
  `import_rules.remember(db, change["remember"], lookups-category of row["category"])` — get the category with
  `db.query(models.Category).filter(models.Category.name == row["category"]).one()`.
- `import_schema`: add `"x-rules": [{"contains": r.text, "category": r.category.name} for r in import_rules.load(db)]`.
- `main.py`: include `import_rules.router`.

- [ ] **Step 4: Run** the file — pass. Run `tests/test_import.py tests/test_transfers.py` (background) — pass.
  Lint. Commit `feat(import): change categories in the preview and remember them as rules`.

### Task 2: Converter applies app rules

**Files:** Modify `tools/converters/common.py`, `tools/converters/bank.py`, `tools/converters/README.md`;
Test `tests/test_converters.py`.

- [ ] **Step 1: Tests** (in `tests/test_converters.py`, new class):

```python
class TestAppRules:
    def schema_with(self, *rules):
        return common.Schema({**SCHEMA, "x-rules": [{"contains": t, "category": c} for t, c in rules]})

    def convert(self, tmp_path, schema, lines):
        return bank.convert(bank_rows(lines, tmp_path=tmp_path), BANK_CONFIG, schema)

    def test_unrecognised_line_gets_the_app_rule(self, tmp_path):
        line = f"{IBAN};2026-09-10 00:00:00.0;Einkauf Velo Muster 09.09.2026, 10:00, Debit Mastercard-Nr. 1;-50.00;100.00;"
        result = self.convert(tmp_path, self.schema_with(("velo muster", "Transportation")), [line])
        assert result.rows[0]["category"] == "Transportation"
        assert result.by_app_rule == 1 and result.unrecognised == []
        assert "1 by app rule" in bank.report(result, tmp_path / "out.csv")

    def test_own_rule_wins(self, tmp_path):
        line = f"{IBAN};2026-09-10 00:00:00.0;Einkauf Bäckerei Muster 09.09.2026, 10:00;-5.00;100.00;"
        result = self.convert(tmp_path, self.schema_with(("Bäckerei", "Healthcare")), [line])
        assert result.rows[0]["category"] == "Groceries" and result.by_app_rule == 0

    def test_sign_must_fit_and_transfer_direction(self, tmp_path):
        credit = f"{IBAN};2026-09-10 00:00:00.0;Gutschrift Velo Muster;30.00;130.00;"
        result = self.convert(tmp_path, self.schema_with(("velo", "Transportation"), ("velo", "Transfer")), [credit])
        assert (result.rows[0]["category"], result.rows[0]["direction"]) == ("Transfer", "in")

    def test_unknown_category_in_rules(self):
        with pytest.raises(common.Problems):
            self.schema_with(("x", "Nope"))
```

  (Use the module's existing IBAN constant for the account in `BANK_CONFIG`; if the module has none, define
  `IBAN = "CH9300762011623852957"` near `BANK_CONFIG`.)

- [ ] **Step 2: Run** — fail. **Step 3: Implement:**
  - `common.Schema.__init__`: `self.rules = []`; for each entry of `schema.get("x-rules", [])`: unknown category →
    collect problem "x-rules: unknown category '<name>'"; raise `Problems` if any; else append
    `(key(contains), name, kind)`.
  - `bank.Result`: `by_app_rule: int = 0`.
  - `bank.convert`: when no own rule matched, before the fallback:

```python
        app_rule = None if rule else next(
            (r for r in schema.rules if r[0] in key(description) and r[2] in ("TRANSFER", "EXPENSE" if debit else "INCOME")),
            None,
        )
```

    If `app_rule`: Transfer → `category=transfer, direction=...`, `result.transfers += 1`; else
    `category=app_rule[1]`, `result.booked += 1`; `result.by_app_rule += 1`; not added to `unrecognised`.
  - `bank.report`: first line adds `, {result.by_app_rule} by app rule` when > 0.
  - README: a paragraph "Rules from the app" under the bank converter.
- [ ] **Step 4: Run** `tests/test_converters.py` — pass; lint. **Step 5: Commit** `feat(tools): bank converter applies the app's import rules`.

### Task 3: Frontend

**Files:** Modify `frontend/src/components/ImportTransactions.tsx`, `frontend/src/components/DataManager.tsx`;
Create `frontend/src/components/ImportRules.tsx`; browser test `scratchpad/e2e/import-rules.js`.

- [ ] **Step 1: Browser test**: log in as Admin; create account "Bank"; Settings; upload a CSV with
  `2026-09-06,Bank,Unsorted,22.10,,Bäckerei Muster,bank:1`; select "Groceries" in the row's dropdown
  (`select[aria-label="Category of line 2"]`); the row shows "Unsorted" struck through; tick "remember"
  (`input[aria-label="Remember line 2 as a rule"]`), change the text field (`input[aria-label="Rule text for
  line 2"]`) to "Bäckerei"; import; the rules list shows "Bäckerei → Groceries"; "Show for converter.toml" shows a
  block containing `match = "Bäckerei"`; upload a second CSV with `2026-10-01,Bank,Unsorted,8,,BÄCKEREI
  Bahnhof,bank:2`; the row shows "Groceries" and "by rule: Bäckerei"; no console errors.
- [ ] **Step 2: Run** — fails. **Step 3: Implement**
  - `ImportTransactions.tsx`: load `/api/v1/categories` once; `useAuth` for `isParent`. State
    `changes: Record<number, { category: string; remember: boolean; text: string }>`. `formData(file, include,
    changes)` appends `changes` as JSON `{line: {category, remember: remember ? text : ""}}`. A dropdown change
    updates `changes` and re-runs `/import/preview` with them (keeps `included`). Rows whose `file_category` type
    is INCOME/EXPENSE get a `<select aria-label="Category of line N">` with the same-type categories and
    "Transfer (out|in)" (value "Transfer"); choosing the file category again removes the change. Changed rows show
    the file category struck through; rows with `rule` show "by rule: <text>". For parents, a changed row shows
    the "remember" checkbox and the text field (prefilled with the description). Reset clears `changes`.
  - `ImportRules.tsx` (parents only, rendered in `DataManager` below the import): loads `/api/v1/import/rules`
    (reload on a `version` prop); each rule: `text → category`, "Show for converter.toml" toggles a `<pre>` with
    `toml` and a "Copy" button (`navigator.clipboard?.writeText`; if unavailable or failing, the text stays
    visible to copy by hand: "Copy by hand: select the text"), "Delete" (confirm). Empty: "No rules yet. Change a
    category in the import preview and tick “remember”."
  - `DataManager.tsx`: `const [rulesVersion, setRulesVersion] = useState(0)`; `ImportTransactions onImported={() =>
    { onDataChanged?.(); setRulesVersion(v => v + 1); }}`; `{user?.role === 'PARENT' && <ImportRules
    version={rulesVersion} />}`.
- [ ] **Step 4:** lint, type-check, build; run `import-rules.js`, `transfers.js`, `month-check.js`.
- [ ] **Step 5: Commit** `feat(frontend): category dropdown and import rules`.
- [ ] **Step 6:** `docs/import-format.md`: a short section "Changing categories in the preview and import rules".
  Commit with the docs.
