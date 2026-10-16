# Manage categories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** System categories found by a fixed key and locked; seeding no longer recreates renamed defaults; parents
add, rename, retype and delete categories in Settings (issue #22).

**Architecture:** `categories.system_key` (migration 0006, unique index). `seed.py` holds the keys, seeds the full
list only into an empty table and ensures the five system categories by key; `seed.system_category(db, key)` replaces
the name lookups. New `backend/app/categories_api.py` (moved GET/POST plus usage, PUT, DELETE). Frontend
`CategoryManager.tsx` in Settings; `Transactions.tsx` uses `system_key`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic; React/TS; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-16-manage-categories-design.md`

## Global Constraints

- Keys: `TRANSFER`, `SETTLE_UP`, `UNSORTED`, `UNKNOWN_EXPENSE`, `OTHER_INCOME`.
- System categories: only the icon may change. Error texts as in the spec.
- Names: trimmed, 1–50 characters, unique ignoring case. Icon ≤ 8 characters. New/changed type only INCOME/EXPENSE.
- Commits end with the Co-Authored-By / Claude-Session lines.

## Review Focus

1. After renaming "Other Income" is refused — but renaming e.g. "Groceries" must not break anything that looked up
   categories by name (grep for remaining name lookups).
2. Seeding on an existing database with a renamed default must not add the old name back.
3. A database where a system category's name row exists without a key gets the key (no duplicate row).
4. Type change while used must be refused (signs of existing bookings).
5. The frontend still recognises Settle up after the switch to `system_key`.

---

### Task 1: System keys, seeding, lookups by key

**Files:** `backend/app/models.py`, `backend/app/seed.py`, `backend/app/migrations/versions/0006_category_keys.py`,
`backend/app/database_setup.py` (HEAD 0006), `api.py`, `common_api.py`, `import_api.py`, `import_rules.py`,
`month_check.py`; tests `tests/test_categories.py` (seeding part), `tests/test_database.py` (migration).

- [ ] **Step 1: Tests**

```python
"""Managing categories: system keys, seeding, and the Settings API (issue #22)."""

import pytest

from app import database, models, seed
from helpers import BASE_URL, add_transaction, category_id, create_account, register

SYSTEM = {"TRANSFER": "Transfer", "SETTLE_UP": "Settle up", "UNSORTED": "Unsorted",
          "UNKNOWN_EXPENSE": "Unknown expense", "OTHER_INCOME": "Other Income"}


def categories(client):
    return {c["name"]: c for c in client.get(f"{BASE_URL}/categories").json()}


class TestSystemCategories:
    def test_keys_in_the_api(self, client):
        listed = categories(client)
        assert {name: listed[name]["system_key"] for name in SYSTEM.values()} == {v: k for k, v in SYSTEM.items()}
        assert listed["Groceries"]["system_key"] is None

    def test_seeding_keeps_renamed_and_deleted_defaults_away(self, client):
        with database.SessionLocal() as db:
            db.query(models.Category).filter(models.Category.name == "Groceries").one().name = "Lebensmittel"
            db.delete(db.query(models.Category).filter(models.Category.name == "Education").one())
            db.commit()
            assert seed.seed_categories(db) == 0
        names = set(categories(client))
        assert "Lebensmittel" in names and "Groceries" not in names and "Education" not in names

    def test_missing_system_category_is_recreated(self, client):
        with database.SessionLocal() as db:
            db.delete(db.query(models.Category).filter(models.Category.system_key == "UNKNOWN_EXPENSE").one())
            db.commit()
            assert seed.seed_categories(db) == 1
            assert seed.system_category(db, "UNKNOWN_EXPENSE").name == "Unknown expense"

    def test_name_without_key_gets_the_key(self, client):
        with database.SessionLocal() as db:
            row = db.query(models.Category).filter(models.Category.system_key == "UNSORTED").one()
            row.system_key = None
            db.commit()
            seed.seed_categories(db)
            assert db.query(models.Category).filter(models.Category.name == "Unsorted").count() == 1
            assert seed.system_category(db, "UNSORTED").name == "Unsorted"
```

  `tests/test_database.py` (append): migration test — at 0005 (downgrade), a database with the five names and no
  column; upgrade sets the keys:

```python
def test_category_keys_migration(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    database_setup.run(engine, command.downgrade, "0005")
    without_link_checks(
        engine,
        "INSERT INTO categories (id, name, type) VALUES ('c1', 'Settle up', 'TRANSFER'), ('c2', 'Groceries', 'EXPENSE')",
    )
    database_setup.setup(engine)
    with engine.connect() as conn:
        keys = dict(conn.execute(text("SELECT name, system_key FROM categories")).all())
    assert keys == {"Settle up": "SETTLE_UP", "Groceries": None}
```

- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement**
  - `models.Category`: `system_key = Column(String, nullable=True, unique=True, index=True)` with a comment (fixed
    key of a category the code needs; null for ordinary ones).
  - `0006`: `batch_alter_table("categories")` add `system_key` String nullable; `create_index("ix_categories_system_key",
    unique=True)`; then `UPDATE categories SET system_key = '<KEY>' WHERE name = '<name>'` for the five. Downgrade:
    drop index and column.
  - `seed.py`: constants `TRANSFER, SETTLE_UP, UNSORTED, UNKNOWN_EXPENSE, OTHER_INCOME` become the **keys**; default
    entries for the five carry `"system_key"`; `seed_categories(db)`: if the table is empty, add all defaults; then for
    each system default: if no row with its key → if a row with its name exists, set the key, else add it; return
    the number of rows added. `system_category(db, key)` → the row (`.one()`).
  - Replace name lookups: `common_api` settle up → `seed.system_category(db, SETTLE_UP)`; `api.py` lines comparing
    `.name == SETTLE_UP` → `.system_key == SETTLE_UP`; `import_api` (`category.system_key == SETTLE_UP`, schema
    `c.system_key != SETTLE_UP`); `import_rules` (`target.system_key != SETTLE_UP`; fallbacks
    `file_category.system_key in (UNSORTED, OTHER_INCOME)`); `month_check` (`system_category(db, UNKNOWN_EXPENSE)` /
    `OTHER_INCOME`).
  - `schemas.Category`: `system_key: Optional[str] = None`.
- [ ] **Step 4: Run** new tests + full suite; lint. **Step 5: Commit** `feat(categories): system categories by fixed key; seeding keeps renamed defaults away`.

### Task 2: Categories API

**Files:** Create `backend/app/categories_api.py`; remove the category routes from `api.py`; `main.py` router;
`schemas.py` (`CategoryCreate` validation, `CategoryUpdate`); tests `tests/test_categories.py`.

- [ ] **Step 1: Tests** (append):

```python
@pytest.fixture
def mum(client):
    return register(client, "mum")


def create(client, headers, name, kind="EXPENSE", icon=None):
    return client.post(f"{BASE_URL}/categories", json={"name": name, "type": kind, "icon": icon}, headers=headers)


def update(client, headers, name, **fields):
    return client.put(f"{BASE_URL}/categories/{category_id(client, name)}", json=fields, headers=headers)


class TestApi:
    def test_create(self, client, mum):
        created = create(client, mum, " Car leasing ", icon="🚙").json()
        assert (created["name"], created["type"], created["icon"], created["system_key"]) == ("Car leasing", "EXPENSE", "🚙", None)
        assert create(client, mum, "car LEASING").json()["detail"] == "A category with that name already exists"
        assert create(client, mum, "Moves", "TRANSFER").status_code == 400
        assert create(client, mum, "  ").status_code == 422
        assert create(client, mum, "x" * 51).status_code == 422

    def test_children_cant_manage(self, client, mum):
        kid = register(client, "kid", role="CHILD", by=mum)
        response = create(client, kid, "Games")
        assert response.status_code == 403 and response.json()["detail"] == "Only parents can manage categories"

    def test_rename_a_default(self, client, mum):
        assert update(client, mum, "Groceries", name="Lebensmittel", icon="🥖").status_code == 200
        assert "Lebensmittel" in categories(client)

    def test_system_category_locked_except_icon(self, client, mum):
        locked = "This category is used by the app and can't be changed"
        assert update(client, mum, "Unsorted", name="Misc").json()["detail"] == locked
        assert update(client, mum, "Unsorted", type="INCOME").json()["detail"] == locked
        assert update(client, mum, "Unsorted", icon="🗂️").status_code == 200
        response = client.delete(f"{BASE_URL}/categories/{category_id(client, 'Unsorted')}", headers=mum)
        assert response.status_code == 400 and response.json()["detail"] == locked

    def test_type_change_only_when_unused(self, client, mum):
        assert update(client, mum, "Gift", type="EXPENSE").status_code == 200
        account = create_account(client, mum)
        add_transaction(client, mum, account, category_id(client, "Gift"), 5)
        response = update(client, mum, "Gift", type="INCOME")
        assert response.status_code == 400
        assert response.json()["detail"] == "Used by 1 transaction; its type can't change"

    def test_delete(self, client, mum):
        create(client, mum, "Car leasing")
        assert client.delete(f"{BASE_URL}/categories/{category_id(client, 'Car leasing')}", headers=mum).status_code == 200
        account = create_account(client, mum)
        for _ in range(2):
            add_transaction(client, mum, account, category_id(client, "Clothing"), 5)
        client.post(f"{BASE_URL}/budgets", json={"category_id": category_id(client, "Clothing"), "limit": 50}, headers=mum)
        response = client.delete(f"{BASE_URL}/categories/{category_id(client, 'Clothing')}", headers=mum)
        assert response.status_code == 409
        assert response.json()["detail"] == "Used by 2 transactions and 1 budget"

    def test_usage(self, client, mum):
        account = create_account(client, mum)
        add_transaction(client, mum, account, category_id(client, "Clothing"), 5)
        usage = client.get(f"{BASE_URL}/categories/usage", headers=mum).json()
        assert usage[category_id(client, "Clothing")] == {"transactions": 1, "budgets": 0, "planned_costs": 0, "import_rules": 0}
        assert category_id(client, "Healthcare") not in usage

    def test_features_still_work_after_renames(self, client, mum):
        # Month check books "Unknown expense" by key, and import rules find the fallback by key
        update(client, mum, "Groceries", name="Lebensmittel")
        assert seed_names_resolve()


def seed_names_resolve():
    with database.SessionLocal() as db:
        return all(seed.system_category(db, key) for key in SYSTEM)
```

- [ ] **Step 2: Run** — fail. **Step 3: Implement** `categories_api.py`:
  - helpers `usage_counts(db) -> dict[str, dict]` (four `GROUP BY category_id` counts), `describe(counts)` →
    "Used by 2 transactions and 1 budget" (non-zero parts; singular/plural; "and" before the last, commas before).
  - `require_parent`; `name_taken(db, name, except_id)` (casefold compare).
  - routes: `GET /categories`, `GET /categories/usage`, `POST /categories`, `PUT /categories/{id}`,
    `DELETE /categories/{id}` per the spec.
  - `schemas.CategoryCreate`: `name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]`,
    `type: CategoryType`, `icon: Optional[str] = Field(default=None, max_length=8)`; `CategoryUpdate` all optional.
- [ ] **Step 4: Run**, full suite, lint. **Step 5: Commit** `feat(categories): add, rename, retype and delete categories (API)`.

### Task 3: Settings screen

**Files:** Create `frontend/src/components/CategoryManager.tsx`; Modify `frontend/src/pages/dashboard/Dashboard.tsx`
(Settings: `{isParent && <CategoryManager />}` after FamilyManager), `frontend/src/accounts.ts` (`system_key`),
`frontend/src/components/Transactions.tsx` (`isSettleUp` by `system_key === 'SETTLE_UP'`); browser test
`e2e/tests/categories.spec.ts`.

- [ ] **Step 1: Browser test**: parent; Settings; add "Car leasing" (expense, 🚙); row shown under Expenses; Edit →
  rename to "Leasing" → shown; Delete (confirm) → gone; the "Unsorted" row shows 🔒 and no Delete button.
- [ ] **Step 2: Run** — fail. **Step 3: Implement** `CategoryManager.tsx` (loads `/categories` and
  `/categories/usage`; add form; three groups; inline edit; Delete only when unused and not system, else a grey
  "used by …" text; errors via `errorMessage`).
- [ ] **Step 4:** lint, type-check, build, all browser tests. **Step 5: Commit** `feat(frontend): manage categories in Settings`.
