# Money in cents and CHF display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Amounts stored as integer cents (API unchanged in francs), `accounts.balance` dropped, money shown as
"CHF 1'234.50" (issues #41, #34).

**Architecture:** `backend/app/money.py` `Money` TypeDecorator; seven model columns use it; migration 0004 converts
data and types (batch mode) and drops the balance column; `database_setup.run` turns link checking off around
migrations. Frontend `finance.money()` becomes the CHF formatter and every money display uses it.

**Tech Stack:** SQLAlchemy 2.1, Alembic 1.20, SQLite; React/TS; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-16-money-in-cents-and-chf-design.md`

## Global Constraints

- API, import/export and converters stay in francs. `None` stays `None`.
- Migration keeps all data; downgrade restores francs and a filled `accounts.balance`.
- Format: `CHF` + space + optional `-` + thousands grouped with `'` + `.` + 2 decimals; never `-0.00`.
- Commits end with the Co-Authored-By / Claude-Session lines.

## Review Focus

1. Rebuilding `transactions` while `settlements` points to it must work (link checking off for the migration).
2. Values like 0.1 + 0.2, 84.3, -22.10 must become 30, 8430, -2210 cents (no 8429 from float error).
3. `Account.balance` must stay in francs (the SUM keeps the `Money` type).
4. A query comparing a `Money` column with a literal must convert the literal to cents.
5. `money(-0.001)` must show `CHF 0.00`.

---

### Task 1: Money type, migration 0004

**Files:** Create `backend/app/money.py`, `backend/app/migrations/versions/0004_money_in_cents.py`; Modify
`backend/app/models.py`, `backend/app/database_setup.py` (`HEAD = "0004"`, link checking off around migrations);
Test `tests/test_database.py`.

- [ ] **Step 1: Tests** (append to `tests/test_database.py`):

```python
from app.money import Money


class TestMoney:
    def test_round_trip(self):
        kind = Money()
        for francs, cents in [(84.3, 8430), (0.1, 10), (-22.1, -2210), (1234.56, 123456), (None, None)]:
            assert kind.process_bind_param(francs, None) == cents
            assert kind.process_result_value(cents, None) == francs

    def test_exact_sums(self, client):
        headers = register(client, "mum")
        account = create_account(client, headers)
        for amount in (0.1, 0.2):
            add_transaction(client, headers, account, category_id(client, "Gift"), amount)
        assert balance(client, headers, account) == 0.3
        with database.engine.connect() as conn:
            assert sorted(conn.execute(text("SELECT amount FROM transactions")).scalars()) == [10, 20]

    def test_query_literal_in_cents(self, client):
        headers = register(client, "mum")
        account = create_account(client, headers)
        add_transaction(client, headers, account, category_id(client, "Groceries"), 5)
        with database.SessionLocal() as db:
            assert db.query(models.Transaction).filter(models.Transaction.amount < -4.99).count() == 1
            assert db.query(models.Transaction).filter(models.Transaction.amount < -5.01).count() == 0


class TestCentsMigration:
    def at_0003_with_floats(self, tmp_path):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        database_setup.run(engine, command.downgrade, "0003")
        without_link_checks(
            engine,
            "INSERT INTO users (id, username, role, is_active, has_allowance) VALUES ('u1', 'mum', 'PARENT', 1, 1)",
            "INSERT INTO accounts (id, user_id, name, balance) VALUES ('a1', 'u1', 'Bank', 0)",
            "INSERT INTO transactions (id, account_id, amount) VALUES ('t1', 'a1', 84.3), ('t2', 'a1', -22.10), "
            "('t3', 'a1', 0.30000000000000004)",
            "INSERT INTO settlements (id, from_user_id, to_user_id, amount, from_transaction_id, to_transaction_id) "
            "VALUES ('s1', 'u1', 'u1', 84.3, 't1', 't2')",
            "INSERT INTO wishes (id, name, owner_id, estimate, best_price, position) VALUES ('w1', 'Bike', 'u1', NULL, 99.95, 1)",
        )
        return engine

    def test_upgrade_converts_to_cents(self, tmp_path):
        engine = self.at_0003_with_floats(tmp_path)
        database_setup.setup(engine)
        with engine.connect() as conn:
            amounts = dict(conn.execute(text("SELECT id, amount FROM transactions")).all())
            assert amounts == {"t1": 8430, "t2": -2210, "t3": 30}
            assert conn.execute(text("SELECT amount FROM settlements")).scalar() == 8430
            assert tuple(conn.execute(text("SELECT estimate, best_price FROM wishes")).one()) == (None, 9995)
            assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert "balance" not in {c["name"] for c in inspect(engine).get_columns("accounts")}
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), models.Base.metadata)
        assert diff == []

    def test_downgrade_restores_francs_and_balance(self, tmp_path):
        engine = self.at_0003_with_floats(tmp_path)
        database_setup.setup(engine)
        database_setup.run(engine, command.downgrade, "0003")
        with engine.connect() as conn:
            assert dict(conn.execute(text("SELECT id, amount FROM transactions")).all()) == {
                "t1": 84.3, "t2": -22.1, "t3": 0.3
            }
            assert conn.execute(text("SELECT balance FROM accounts")).scalar() == 62.5
```

- [ ] **Step 2: Run** — fail (no `app.money`).
- [ ] **Step 3: Implement**
  - `money.py`:

```python
"""Money columns: stored as integer cents, handed to the code (and the API) as francs."""

from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.types import TypeDecorator


class Money(TypeDecorator):
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Optional[float], dialect) -> Optional[int]:
        return None if value is None else round(value * 100)

    def process_result_value(self, value: Optional[int], dialect) -> Optional[float]:
        return None if value is None else value / 100
```

  - `models.py`: the seven columns `Column(Money)` (keep `nullable`); remove `stored_balance`; `Account.balance`:
    `select(func.coalesce(func.sum(Transaction.amount), 0))…` (no `round`; check the type stays `Money` — if
    `coalesce` loses it, use `type_coerce(…, Money)`).
  - `0004_money_in_cents.py`: `MONEY = {"transactions": ["amount"], "budgets": ["limit"], "assets": ["price"],
    "settlements": ["amount"], "planned_costs": ["amount"], "wishes": ["estimate", "best_price"]}`; upgrade: per
    table, per column `UPDATE {table} SET "{col}" = CAST(ROUND("{col}" * 100) AS INTEGER) WHERE "{col}" IS NOT NULL`,
    then `batch_alter_table(table)` → `alter_column(col, type_=sa.Integer(), existing_type=sa.Float())`; then
    `batch_alter_table("accounts")` → `drop_column("balance")`. Downgrade: reverse (`add_column("balance", Float)`,
    fill with `SELECT ROUND(COALESCE(SUM(amount), 0), 2)` per account after converting amounts back with `/ 100.0`).
    Quote `"limit"` (SQL keyword).
  - `database_setup.run`: for SQLite, on a fresh connection: `exec_driver_sql("PRAGMA foreign_keys=OFF")` before
    `begin()`, run the action inside `with connection.begin():`, then `PRAGMA foreign_keys=ON`. `HEAD = "0004"`.
- [ ] **Step 4: Run** `tests/test_database.py`, then the full suite; lint. **Step 5: Commit** `feat(db): store money in integer cents`.

### Task 2: CHF display

**Files:** `frontend/src/finance.ts`, `Dashboard.tsx`, `Analytics.tsx`, `BudgetManager.tsx`; e2e specs.

- [ ] **Step 1: Update browser test expectations** first: `$45.50` → `CHF 45.50`, `$3000.00` → `CHF 3'000.00`,
  `$2954.50` → `CHF 2'954.50`, `$45.50 / $200.00` → `CHF 45.50 / CHF 200.00`, wishes `Total $1220.00` →
  `Total CHF 1'220.00`, `$800.00`/`$920.00` → `CHF 800.00`/`CHF 920.00`, `best $99.50` → `best CHF 99.50`,
  month check `not tracked $50.00` → `not tracked CHF 50.00`. Run — fail.
- [ ] **Step 2: Implement** `finance.money`:

```ts
// Swiss francs, the same text in every browser: CHF 1'234.50, CHF -22.10 (Intl's output differs between browsers)
export function money(value: number): string {
    const cents = Math.round(value * 100);
    const francs = Math.floor(Math.abs(cents) / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "'");
    const rest = (Math.abs(cents) % 100).toString().padStart(2, '0');
    return `CHF ${cents < 0 ? '-' : ''}${francs}.${rest}`;
}
```

  and replace every `$${x.toFixed(2)}` / `${x.toFixed(2)}` money display: Dashboard (my balance, account cards,
  transaction amounts keep their `+` prefix for income: `+ CHF 300.00`, delete confirm text), Analytics (cards, child
  costs, category list; `<Tooltip formatter={(v) => money(Number(v))} />` on the three charts), BudgetManager
  (spent/limit, exceeded text). CommonBudget line 126 is a form value — leave it.
- [ ] **Step 3:** lint, type-check, build; all browser tests; `grep` shows no `$${` or money `toFixed(2)` left.
- [ ] **Step 4: Commit** `feat(frontend): show money in CHF`.
