# Database foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alembic migrations applied on start-up, SQLite foreign keys enforced, account balances calculated from
transactions (issue #29).

**Architecture:** `database.py` turns on `PRAGMA foreign_keys` per connection. `models.Account.balance` becomes a
`column_property` (correlated SUM). New `app/database_setup.py` decides catch-up/stamp/upgrade and logs
`foreign_key_check`; migrations in `app/migrations/` (0001 baseline, 0002 repair, 0003 indexes); `main.py` calls
`database_setup.setup(engine)`; `migrate.py` is removed.

**Tech Stack:** SQLAlchemy 2.1, Alembic 1.20.0, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-database-foundation-design.md`

## Global Constraints

- Nothing in a migration deletes data; 0002 only sets broken optional links to NULL.
- Start-up never fails because of old link problems; it logs them (warning, per table with count).
- The API's `balance` field and all its readers stay unchanged.
- Tests keep `create_all` for speed; migration tests use their own temporary database files.
- Commits end with the Co-Authored-By / Claude-Session lines.

## Review Focus

1. A database from before this change (no `alembic_version`) must be caught up, stamped and upgraded, keeping data.
2. A delete path that deletes a parent before its children must fail loudly now (tests run with FKs on).
3. The calculated balance must round to cents (float sums like 0.1 + 0.2).
4. `alembic_version` must not be created by the tests' `create_all` path in a way that breaks the old-database test.
5. Running start-up twice must be a no-op the second time.

---

### Task 1: Enforced foreign keys

**Files:** `backend/app/database.py`; tests `tests/test_database.py` (new).

- [ ] **Step 1: Test** (`tests/test_database.py`):

```python
"""Database foundation: enforced links, calculated balances, migrations on start-up (issue #29)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import database
from helpers import BASE_URL, add_transaction, balance, category_id, create_account, register


class TestForeignKeys:
    def test_enforced(self):
        with database.engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            with pytest.raises(IntegrityError):
                conn.execute(
                    text("INSERT INTO transactions (id, account_id, amount) VALUES ('t1', 'no-such-account', 1)")
                )
```

- [ ] **Step 2: Run** — fails (`PRAGMA foreign_keys` is 0).
- [ ] **Step 3: Implement** in `database.py` after `engine = create_engine(...)`:

```python
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(dbapi_connection, _record):
        # SQLite only checks the declared links when asked to, per connection
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```

  (`from sqlalchemy import create_engine, event`.)
- [ ] **Step 4: Run** the new test, then the **full suite**. Any failure is a delete path with the wrong order or
  a missing cleanup: fix it in the code (not the test) with the smallest change, and note each in the commit message.
  `conftest.fresh_db` uses `drop_all` — if that fails with FKs on, it's fine to drop in reverse dependency order
  (`drop_all` already sorts tables) or wrap it in `PRAGMA foreign_keys=OFF` for the test reset only.
- [ ] **Step 5: Commit** `feat(db): enforce SQLite foreign keys`.

### Task 2: Calculated balances

**Files:** `backend/app/models.py`, `backend/app/crud.py`, `backend/app/common_api.py`; test `tests/test_database.py`.

- [ ] **Step 1: Tests** (append):

```python
class TestBalances:
    def test_sum_of_transactions(self, client):
        headers = register(client, "mum")
        account = create_account(client, headers)
        assert balance(client, headers, account) == 0
        gift, groceries = category_id(client, "Gift"), category_id(client, "Groceries")
        first = add_transaction(client, headers, account, gift, 0.1).json()
        add_transaction(client, headers, account, gift, 0.2)
        assert balance(client, headers, account) == 0.3
        client.put(f"{BASE_URL}/transactions/{first['id']}", json={"amount": 10, "category_id": groceries}, headers=headers)
        assert balance(client, headers, account) == -9.8
        client.delete(f"{BASE_URL}/transactions/{first['id']}", headers=headers)
        assert balance(client, headers, account) == 0.2

    def test_stored_column_is_not_used(self, client):
        headers = register(client, "mum")
        account = create_account(client, headers)
        add_transaction(client, headers, account, category_id(client, "Gift"), 5)
        with database.engine.begin() as conn:
            conn.execute(text("UPDATE accounts SET balance = 999"))
        assert balance(client, headers, account) == 5
```

- [ ] **Step 2: Run** — `test_stored_column_is_not_used` fails (balance 999).
- [ ] **Step 3: Implement**
  - `models.Account`: `stored_balance = Column("balance", Float, default=0.0)` with comment "Unused since balances
    are calculated; dropped with the move to cents". After the `Transaction` class:

```python
# An account's balance is the sum of its transactions (calculated, so it can't drift)
Account.balance = column_property(
    select(func.round(func.coalesce(func.sum(Transaction.amount), 0.0), 2))
    .where(Transaction.account_id == Account.id)
    .correlate_except(Transaction)
    .scalar_subquery()
)
```

    (imports: `from sqlalchemy import select, func` and `from sqlalchemy.orm import column_property`).
  - `crud.create_account`: drop `balance=0.0`. `crud.create_transaction` / `update_transaction` /
    `delete_transaction`: remove the balance updates (and the `get_account` lookups only used for them).
  - `common_api` settle-up: remove the two balance lines.
  - Any response built right after a change must show the new balance: `db.refresh(account)` where an account is
    returned after a write (create/update account already refresh).
- [ ] **Step 4: Run** new tests and the full suite. **Step 5: Commit** `feat(db): calculate balances from transactions`.

### Task 3: Alembic and start-up

**Files:** `backend/requirements.txt`, `backend/alembic.ini`, `backend/app/migrations/{env.py,script.py.mako,versions/0001_baseline.py,0002_repair_links.py,0003_indexes.py}`,
`backend/app/database_setup.py`, `backend/app/main.py`; delete `backend/app/migrate.py`; tests in
`tests/test_database.py` (and move `test_migration_adds_reference` from `tests/test_import.py` to the old-database
test).

**Interfaces — Produces:** `database_setup.setup(engine) -> None`; `database_setup.alembic_config(engine) -> Config`.

- [ ] **Step 1: Tests** (append):

```python
import logging
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import database_setup, models


def sqlite(tmp_path: Path, name: str = "app.db"):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    database.enable_foreign_keys(engine)
    return engine


class TestMigrations:
    def test_empty_database_matches_the_models(self, tmp_path):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), models.Base.metadata)
        assert diff == []

    def test_start_up_twice(self, tmp_path):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        database_setup.setup(engine)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == database_setup.HEAD

    def test_old_database_is_caught_up(self, tmp_path):
        engine = sqlite(tmp_path)
        # As made before migrations: create_all of an older schema, without a later column and table
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users (id VARCHAR PRIMARY KEY, username VARCHAR, pin_hash VARCHAR, "
                              "role VARCHAR(6), privacy_enabled BOOLEAN, is_active BOOLEAN, settings JSON)"))
            conn.execute(text("INSERT INTO users (id, username, role, is_active) VALUES ('u1', 'mum', 'PARENT', 1)"))
        database_setup.setup(engine)
        tables = set(inspect(engine).get_table_names())
        assert {"wishes", "import_rules", "alembic_version"} <= tables
        assert "has_allowance" in {c["name"] for c in inspect(engine).get_columns("users")}
        with engine.connect() as conn:
            assert conn.execute(text("SELECT username FROM users")).scalar() == "mum"

    def test_repair_clears_broken_optional_links(self, tmp_path):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        command_downgrade_to(engine, "0001")
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("INSERT INTO users (id, username, role, is_active, has_allowance) VALUES ('u1','mum','PARENT',1,1)"))
            conn.execute(text("INSERT INTO accounts (id, user_id, name) VALUES ('a1', 'u1', 'Bank')"))
            conn.execute(text("INSERT INTO transactions (id, account_id, amount, member_id, split_id, asset_id) "
                              "VALUES ('t1', 'a1', -5, 'gone', 'gone', 'gone')"))
        database_setup.setup(engine)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT member_id, split_id, asset_id, account_id FROM transactions")).one()
        assert tuple(row) == (None, None, None, "a1")

    def test_start_up_logs_broken_links(self, tmp_path, caplog):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("INSERT INTO budgets (id, user_id) VALUES ('b1', 'gone')"))
        with caplog.at_level(logging.WARNING):
            database_setup.setup(engine)
        assert "budgets: 1 row" in caplog.text
```

  with a helper `command_downgrade_to(engine, revision)` using `alembic.command.downgrade(database_setup.alembic_config(engine), revision)`.
  Note: `PRAGMA foreign_keys=OFF` inside a transaction is ignored by SQLite — execute it on a connection outside
  `begin()` (use `engine.connect()` with autocommit / `conn.exec_driver_sql` before starting the transaction);
  adjust the helper accordingly.
- [ ] **Step 2: Run** — fail (no `database_setup`).
- [ ] **Step 3: Implement**
  - `database.py`: refactor the listener into `enable_foreign_keys(engine)` and call it for the app engine.
  - `alembic.ini` (`script_location = app:migrations`, `sqlalchemy.url` unset; logging sections minimal).
  - `migrations/env.py`: online mode using `config.attributes["connection"]` when given, else an engine from
    `DATABASE_URL`; `target_metadata = models.Base.metadata`; `render_as_batch=True` (SQLite).
  - `0001_baseline.py`: generated by `alembic revision --autogenerate` against an empty database, checked by hand
    to contain every table and FK; `down_revision = None`.
  - `0002_repair_links.py`: three `UPDATE transactions SET <col> = NULL WHERE <col> IS NOT NULL AND <col> NOT IN
    (SELECT id FROM <parent>)`; downgrade: no-op.
  - `0003_indexes.py`: `op.create_index("ix_transactions_account_date", "transactions", ["account_id", "date"])`,
    `op.create_index("ix_transactions_reference", "transactions", ["reference"])`; downgrade drops them. Add the same
    indexes to the models (`__table_args__`) so `compare_metadata` stays empty.
  - `database_setup.py`: `HEAD = "0003"`; `NEW_COLUMNS` (moved from `migrate.py`); `catch_up(engine)` (the old
    `create_all(tables of the baseline)` + add missing columns) — careful: `create_all` with today's models would
    also create the 0003 indexes; call `create_all` and then stamp `0001` and upgrade; 0003 must therefore use
    `if_not_exists=True` for its indexes; `setup(engine)`:

```python
def setup(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    config = alembic_config(engine)
    if tables and "alembic_version" not in tables:
        catch_up(engine)
        command.stamp(config, "0001")
    command.upgrade(config, "head")
    log_broken_links(engine)
```

  - `main.py`: replace `create_all` + `add_missing_columns` with `database_setup.setup(database.engine)`.
  - Delete `migrate.py`; move its test from `test_import.py` (`test_migration_adds_reference`) into
    `TestMigrations.test_old_database_is_caught_up` (already covers a missing column).
- [ ] **Step 4: Run** `tests/test_database.py`, the full suite, the browser tests. Lint.
- [ ] **Step 5: Commit** `feat(db): Alembic migrations applied on start-up`.

### Task 4: Docs

- [ ] `README_DOCKER.md`: a short "Database updates" section: migrations run on start-up, backup by `nas-update.sh`,
  rollback = previous image + backup. `backend/` developer note on `alembic revision --autogenerate`. Commit.
