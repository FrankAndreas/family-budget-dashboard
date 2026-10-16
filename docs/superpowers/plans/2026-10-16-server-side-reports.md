# Server-side reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Budgets' spending and the Analytics numbers come from the server, in Swiss time (issue #30).

**Architecture:** New `backend/app/reports.py`: Swiss-time helpers, a query for a scope's non-transfer bookings, the
budget spending, the summary, and the `GET /reports/summary` router. `api.py`'s budget routes return
`reports.budget_out`. Frontend `BudgetManager.tsx` and `Analytics.tsx` display server numbers;
`fetchTransactionsForUsers` goes.

**Tech Stack:** FastAPI, SQLAlchemy, zoneinfo; React 19, recharts, date-fns; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-16-server-side-reports-design.md`

## Global Constraints

- Swiss calendar (`Europe/Zurich`); stored dates naive UTC; `reports.today()` is the only clock (tests replace it).
- Transfers never count; income/expense by category type; amounts positive, rounded to cents.
- Access via `privacy.check_user_access` (view is enough); invalid range → 422.
- The screens look and behave as before. Commits end with the Co-Authored-By / Claude-Session lines.

## Review Focus

1. Month starts across a year boundary (`3months` in January, `months` list in February).
2. A booking at 23:30 Swiss time on the last day of a month (UTC already the next day? no: 21:30 UTC same day; and
   00:30 Swiss on the 1st = 22:30 UTC the day before).
3. Summer/winter time: day boundaries via zoneinfo, not a fixed offset.
4. `DELETE /budgets/{id}` still returns a valid Budget (new fields have defaults).
5. A child's own scope: `by_child` empty.

---

### Task 1: reports module and budget spending

**Files:** Create `backend/app/reports.py`, `tests/test_reports.py`; Modify `backend/app/schemas.py`
(`Budget` + `spent: float = 0.0`, `percentage: float = 0.0`; new `ReportSummary` models), `backend/app/api.py`
(budget routes return `reports.budget_out(db, budget)`), `backend/app/main.py` (router).

- [ ] **Step 1: Tests** `tests/test_reports.py`:

```python
"""Budgets and analytics calculated on the server, in Swiss time (issue #30)."""

from datetime import date

import pytest

from app import reports
from helpers import BASE_URL, add_transaction, category_id, create_account, register, user_id

TODAY = date(2026, 10, 15)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(reports, "today", lambda: TODAY)


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    return {"headers": headers, "account": create_account(client, headers), "id": user_id(client, headers, "mum")}


def book(client, who, category, amount, when, **extra):
    response = add_transaction(client, who["headers"], who["account"], category_id(client, category), amount, date=when, **extra)
    assert response.status_code == 200, response.text
    return response.json()


def summary(client, who, period="month", **params):
    response = client.get(f"{BASE_URL}/reports/summary", params={"range": period, **params}, headers=who["headers"])
    assert response.status_code == 200, response.text
    return response.json()


class TestSummary:
    def test_totals_and_categories(self, client, mum):
        book(client, mum, "Salary", 5000, "2026-10-01")
        book(client, mum, "Groceries", 80.5, "2026-10-03")
        book(client, mum, "Groceries", 20, "2026-10-04")
        book(client, mum, "Healthcare", 150, "2026-10-05")
        data = summary(client, mum)
        assert (data["income"], data["expenses"]) == (5000.0, 250.5)
        assert [(c["name"], c["amount"]) for c in data["by_category"]] == [("Healthcare", 150.0), ("Groceries", 100.5)]

    def test_transfers_never_count(self, client, mum):
        from test_import import csv_file, upload

        lines = csv_file("2026-10-02,Bank,Transfer,300,out,Savings,,", header="date,account,category,amount,direction,description,for,item")
        assert upload(client, mum["headers"], lines, path="import").status_code == 200
        data = summary(client, mum)
        assert (data["income"], data["expenses"], data["by_category"]) == (0.0, 0.0, [])

    @pytest.mark.parametrize(
        "period, expected",
        [("month", 10.0), ("3months", 10.0 + 20.0), ("year", 10.0 + 20.0 + 40.0), ("all", 10.0 + 20.0 + 40.0 + 80.0)],
    )
    def test_ranges(self, client, mum, period, expected):
        book(client, mum, "Groceries", 10, "2026-10-01")
        book(client, mum, "Groceries", 20, "2026-08-01")
        book(client, mum, "Groceries", 40, "2026-01-01")
        book(client, mum, "Groceries", 80, "2025-12-31")
        assert summary(client, mum, period)["expenses"] == expected

    def test_swiss_days_and_months(self, client, mum):
        book(client, mum, "Groceries", 7, "2026-09-30T21:30:00Z")  # 23:30 on 30 September in Zurich
        book(client, mum, "Groceries", 3, "2026-09-30T22:30:00Z")  # 00:30 on 1 October in Zurich
        data = summary(client, mum)
        assert data["expenses"] == 3.0
        assert data["days"][0] == {"date": "2026-10-01", "income": 0.0, "expenses": 3.0}
        assert len(data["days"]) == 31
        months = {m["month"]: m["expenses"] for m in data["months"]}
        assert list(months) == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
        assert (months["2026-09"], months["2026-10"]) == (7.0, 3.0)

    def test_months_across_new_year(self, client, mum, monkeypatch):
        monkeypatch.setattr(reports, "today", lambda: date(2027, 2, 10))
        assert [m["month"] for m in summary(client, mum)["months"]] == [
            "2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"
        ]
        book(client, mum, "Groceries", 5, "2026-12-15")
        assert summary(client, mum, "3months")["expenses"] == 5.0

    def test_children(self, client, mum):
        client.post(f"{BASE_URL}/members", json={"username": "Kim"}, headers=mum["headers"])
        kim = user_id(client, mum["headers"], "Kim")
        book(client, mum, "Clothing", 60, "2026-10-02", member_id=kim)
        book(client, mum, "Clothing", 40, "2026-10-02")
        assert summary(client, mum)["by_child"] == [{"member_id": kim, "name": "Kim", "amount": 60.0}]

    def test_access(self, client, mum):
        dad = register(client, "dad")
        response = client.get(f"{BASE_URL}/reports/summary", params={"user_id": mum["id"]}, headers=dad)
        assert response.status_code == 403
        client.put(f"{BASE_URL}/shares/{user_id(client, dad, 'dad')}", json={"level": "VIEW"}, headers=mum["headers"])
        book(client, mum, "Groceries", 12, "2026-10-02")
        response = client.get(f"{BASE_URL}/reports/summary", params={"user_id": mum["id"]}, headers=dad)
        assert response.json()["expenses"] == 12.0
        assert client.get(f"{BASE_URL}/reports/summary", params={"range": "week"}, headers=dad).status_code == 422


class TestBudgets:
    def budget(self, client, who, category, limit, period="MONTHLY"):
        body = {"category_id": category_id(client, category), "limit": limit, "period": period}
        response = client.post(f"{BASE_URL}/budgets", json=body, headers=who["headers"])
        assert response.status_code == 200, response.text
        return response.json()

    def test_spent_this_month_and_year(self, client, mum):
        book(client, mum, "Groceries", 30, "2026-10-02")
        book(client, mum, "Groceries", 50, "2026-03-02")
        book(client, mum, "Healthcare", 99, "2026-10-02")
        monthly = self.budget(client, mum, "Groceries", 200)
        assert (monthly["spent"], monthly["percentage"]) == (30.0, 15.0)
        self.budget(client, mum, "Clothing", 1000, "YEARLY")
        listed = {b["period"]: b for b in client.get(f"{BASE_URL}/budgets", headers=mum["headers"]).json()}
        assert listed["MONTHLY"]["spent"] == 30.0
        assert listed["YEARLY"]["spent"] == 0.0

    def test_yearly(self, client, mum):
        book(client, mum, "Groceries", 30, "2026-10-02")
        book(client, mum, "Groceries", 50, "2026-03-02")
        book(client, mum, "Groceries", 70, "2025-12-02")
        yearly = self.budget(client, mum, "Groceries", 300, "YEARLY")
        assert (yearly["spent"], yearly["percentage"]) == (80.0, 26.7)

    def test_only_the_owners_accounts(self, client, mum):
        dad = {"headers": register(client, "dad")}
        dad["account"] = create_account(client, dad["headers"])
        book(client, dad, "Groceries", 500, "2026-10-02")
        assert self.budget(client, mum, "Groceries", 100)["spent"] == 0.0

    def test_delete_still_works(self, client, mum):
        budget = self.budget(client, mum, "Groceries", 100)
        assert client.delete(f"{BASE_URL}/budgets/{budget['id']}", headers=mum["headers"]).status_code == 200
```

- [ ] **Step 2: Run** — fail (no `app.reports`).
- [ ] **Step 3: Implement** `reports.py`:

```python
"""Budgets' spending and the Analytics numbers, calculated on the server in Swiss time.

A scope is one person's money: their accounts only. Transfers never count; income and expenses follow the
category type.
"""

from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from . import auth, database, models, privacy

router = APIRouter()

ZURICH = ZoneInfo("Europe/Zurich")
Range = Literal["month", "3months", "year", "all"]
INCOME, EXPENSE = models.CategoryType.INCOME, models.CategoryType.EXPENSE


def today() -> date:
    return datetime.now(ZURICH).date()


def utc_start(day: date) -> datetime:
    """Midnight of a Swiss day, as a stored (naive UTC) date."""
    return datetime.combine(day, time(), ZURICH).astimezone(timezone.utc).replace(tzinfo=None)


def swiss_day(value: datetime) -> date:
    return value.replace(tzinfo=timezone.utc).astimezone(ZURICH).date()


def month_start(day: date, back: int = 0) -> date:
    months = day.year * 12 + day.month - 1 - back
    return date(months // 12, months % 12 + 1, 1)


def range_start(period: str, day: date) -> Optional[date]:
    return {"month": month_start(day), "3months": month_start(day, 2), "year": date(day.year, 1, 1)}.get(period)


def cents(value: float) -> float:
    return round(value + 0.0, 2)


def bookings(db: Session, owner_id: str, since: Optional[date]) -> list[tuple[models.Transaction, models.Category]]:
    """The owner's income and expenses (no transfers) from a Swiss day on."""
    query = (
        db.query(models.Transaction, models.Category)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .join(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(models.Account.user_id == owner_id, models.Category.type.in_([INCOME, EXPENSE]))
    )
    if since:
        query = query.filter(models.Transaction.date >= utc_start(since))
    return query.all()


def budget_out(db: Session, budget: models.Budget) -> dict:
    day = today()
    since = month_start(day) if budget.period == "MONTHLY" else date(day.year, 1, 1)
    spent = cents(
        sum(abs(t.amount) for t, c in bookings(db, budget.user_id, since) if c.type == EXPENSE and c.id == budget.category_id)
    )
    percentage = round(spent / budget.limit * 100, 1) if budget.limit else 0.0
    return {
        "id": budget.id, "user_id": budget.user_id, "category_id": budget.category_id, "limit": budget.limit,
        "period": budget.period, "spent": spent, "percentage": percentage,
    }


def summary(db: Session, owner: models.User, period: str, day: date) -> dict:
    start = range_start(period, day)
    six_months = month_start(day, 5)
    rows = bookings(db, owner.id, None if start is None else min(start, six_months))
    totals = {INCOME: 0.0, EXPENSE: 0.0}
    by_category: dict[str, list] = {}
    by_child: dict[str, float] = defaultdict(float)
    months = {month_start(day, back).strftime("%Y-%m"): {INCOME: 0.0, EXPENSE: 0.0} for back in range(5, -1, -1)}
    first = month_start(day)
    days = {}
    current = first
    while current.month == first.month:
        days[current.isoformat()] = {INCOME: 0.0, EXPENSE: 0.0}
        current = date.fromordinal(current.toordinal() + 1)
    for transaction, category in rows:
        local = swiss_day(transaction.date)
        amount = abs(transaction.amount)
        if start is None or local >= start:
            totals[category.type] += amount
            if category.type == EXPENSE:
                by_category.setdefault(category.id, [category.name, 0.0])[1] += amount
                if transaction.member_id:
                    by_child[transaction.member_id] += amount
        if local.strftime("%Y-%m") in months:
            months[local.strftime("%Y-%m")][category.type] += amount
        if local.isoformat() in days:
            days[local.isoformat()][category.type] += amount
    names = {u.id: u.username for u in db.query(models.User).filter(models.User.id.in_(list(by_child)))}
    is_parent = owner.role == models.UserRole.PARENT
    return {
        "range": period,
        "income": cents(totals[INCOME]),
        "expenses": cents(totals[EXPENSE]),
        "by_category": sorted(
            ({"category_id": cid, "name": name, "amount": cents(amount)} for cid, (name, amount) in by_category.items()),
            key=lambda row: -row["amount"],
        ),
        "by_child": sorted(
            ({"member_id": mid, "name": names.get(mid, ""), "amount": cents(a)} for mid, a in by_child.items())
            if is_parent else [],
            key=lambda row: -row["amount"],
        ),
        "months": [{"month": m, "income": cents(v[INCOME]), "expenses": cents(v[EXPENSE])} for m, v in months.items()],
        "days": [{"date": d, "income": cents(v[INCOME]), "expenses": cents(v[EXPENSE])} for d, v in days.items()],
    }


@router.get("/reports/summary")
def get_summary(
    user_id: Optional[str] = None,
    period: Range = Query("month", alias="range"),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    owner = privacy.check_user_access(db, current_user, user_id) if user_id else current_user
    return summary(db, owner, period, today())
```

  `api.py`: `get_budgets` → `[reports.budget_out(db, b) for b in crud.get_budgets(db, owner.id)]`; `create_budget`,
  `update_budget` → `reports.budget_out(db, …)`. `schemas.Budget`: add `spent: float = 0.0`, `percentage: float = 0.0`.
  `main.py`: include `reports.router`.
- [ ] **Step 4: Run** the file and the full suite; lint. **Step 5: Commit** `feat(reports): budgets' spending and analytics numbers calculated on the server`.

### Task 2: Frontend

**Files:** `frontend/src/components/BudgetManager.tsx`, `frontend/src/components/Analytics.tsx`, `frontend/src/api.ts`;
Create `e2e/tests/reports.spec.ts`.

- [ ] **Step 1: Browser test** `reports.spec.ts`: new parent; account "Bank" via API; book Salary 3000 and Groceries
  45.50 today (Swiss date) via API; Groceries monthly budget 200 via API; log in; Budgets tab shows "$45.50" (spent)
  for Groceries; Analytics tab: "Income (This Month)" card shows "$3000.00", "Expenses (This Month)" shows "$45.50",
  and the category list shows "Groceries" with "$45.50"; no console errors.
- [ ] **Step 2: Run** — it may already pass against the old frontend (same numbers); that's fine: it guards the
  change. Note the result.
- [ ] **Step 3: Implement**
  - `BudgetManager.tsx`: `loadBudgetsWithSpending` loads `/budgets` (with `user_id` as now) and `/categories`, maps
    each budget to `{...budget, category}` using the server's `spent` and `percentage`.
  - `Analytics.tsx`: state `summary` from `GET /reports/summary` with `user_id` = scope's `budgetOwnerId` (absent for
    the own scope) and `range`; reload when scope or range changes. `dailyData` = `summary.days` mapped to
    `{date: format(parseISO(d.date), 'MMM dd'), income, expenses, net}`; `monthlyData` = `summary.months` mapped to
    `{month: format(parseISO(m.month + '-01'), 'MMM'), income, expenses, savings}`; `categoryData` =
    `by_category` → `{name, value}`; totals from `income`/`expenses`; `childCosts` from `by_child`.
  - `api.ts`: remove `fetchTransactionsForUsers`.
- [ ] **Step 4:** lint, type-check, build; all browser tests. **Step 5: Commit** `feat(frontend): budgets and analytics show the server's numbers`.
