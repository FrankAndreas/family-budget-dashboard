# Budget and accounts, month check: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep budget and accounting apart on screen (Overview → "Accounts" tab), add the account type Clearing,
and a month check that books each completed month's gap on a clearing account as "Unknown expense" (or "Other
Income").

**Architecture:** One new backend module `month_check.py` (router + pure helpers) computes per-month sums of a
clearing account's bookings in Swiss months and books the gap through the existing `crud.create_transaction`. The
frontend gets one new component `MonthCheck.tsx` shown on the Accounts tab.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, `zoneinfo` (+ `tzdata` package for slim images); React 19, TS, Tailwind.

**Spec:** `docs/superpowers/specs/2026-10-15-budget-and-accounts-design.md`

## Global Constraints

- Month = calendar month in `Europe/Zurich`. Stored dates are naive UTC.
- Differences below 0.01 count as 0; amounts rounded to cents.
- Booking: last day of the month 12:00 UTC, description `Month check <Month name> <YYYY>`, reference
  `month-check:<YYYY-MM>`, category "Unknown expense" (positive gap) or "Other Income" (negative gap).
- Error texts: "Only clearing accounts have a month check", "Only completed months can be checked",
  "This month adds up already", 409 "Already booked; delete the month-check booking to book the new difference".
- No real data in tests or docs (public repo).
- Commits end with the Co-Authored-By / Claude-Session lines.

## Review Focus

1. A booking near midnight on the last day of a month (UTC vs Swiss time) lands in the Swiss month → test in Task 2.
2. Float sums like 0.1 + 0.2 − 0.3 must count as "adds up" → test in Task 2.
3. Booking the same month twice (double click, two parents) must not book twice → 409 test in Task 2.
4. A user with view-only access must see the list but not book → test in Task 2.
5. Re-render loops in the frontend component when the parent passes a freshly filtered array → effect keyed on
   the account ids string, checked in the browser test (Task 3).

---

### Task 1: Account type Clearing, category Unknown expense

**Files:**
- Modify: `backend/app/models.py` (`AccountType`), `backend/app/seed.py`, `backend/requirements.txt`
- Test: `tests/test_month_check.py` (new), `tests/test_import.py` / `tests/test_review_fixes.py` (category count 19 → 20)

**Interfaces:**
- Produces: `models.AccountType.CLEARING`; `seed.UNKNOWN_EXPENSE = "Unknown expense"`.

- [ ] **Step 1: Write the failing tests** (`tests/test_month_check.py`)

```python
"""Month check on clearing accounts: each completed month's own bookings add up to 0; the gap is booked once."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from helpers import BASE_URL, add_transaction, balance, category_id, create_account, register, user_id


def clearing(client, headers, name="Migros"):
    return client.post(f"{BASE_URL}/accounts", json={"name": name, "type": "CLEARING"}, headers=headers).json()["id"]


class TestSetup:
    def test_unknown_expense_seeded(self, client):
        types = {c["name"]: c["type"] for c in client.get(f"{BASE_URL}/categories").json()}
        assert types["Unknown expense"] == "EXPENSE"

    def test_clearing_account_created_and_switched(self, client):
        headers = register(client, "mum")
        bank = create_account(client, headers, "Migros")
        assert client.put(f"{BASE_URL}/accounts/{bank}", json={"type": "CLEARING"}, headers=headers).status_code == 200
        created = clearing(client, headers, "Card")
        types = {a["id"]: a["type"] for a in client.get(f"{BASE_URL}/accounts", headers=headers).json()}
        assert types[bank] == "CLEARING" and types[created] == "CLEARING"
```

- [ ] **Step 2: Run** `$V/python -m pytest tests/test_month_check.py -q -p no:warnings` — Expected: 2 failed
  (KeyError 'Unknown expense'; 422 on type CLEARING).

- [ ] **Step 3: Implement**
  - `models.AccountType`: add `CLEARING = "CLEARING"` with comment `# Money in by transfer, out by receipts; should
    be 0 at the end of each month (month check)`.
  - `seed.py`: `UNKNOWN_EXPENSE = "Unknown expense"` constant; in `DEFAULT_CATEGORIES` after Unsorted/Reimbursements:
    `# The month check's booking for money on a clearing account without receipts` /
    `{"name": UNKNOWN_EXPENSE, "type": "EXPENSE", "icon": "🫥"}`.
  - `backend/requirements.txt`: add `tzdata==2025.2` (zoneinfo data for the slim image).
  - Category count assertions in `tests/test_import.py` and `tests/test_review_fixes.py`: 19 → 20 (grep `19`).

- [ ] **Step 4: Run** the new file plus `tests/test_import.py tests/test_review_fixes.py` — Expected: all pass.

- [ ] **Step 5: Commit** `feat(accounts): account type Clearing and the category Unknown expense`

### Task 2: Month check API

**Files:**
- Create: `backend/app/month_check.py`
- Modify: `backend/app/main.py` (include router)
- Test: `tests/test_month_check.py`

**Interfaces:**
- Consumes: `models.AccountType.CLEARING`, `seed.UNKNOWN_EXPENSE`, `privacy.check_account_access(db, user, id,
  write)`, `crud.create_transaction(db, schemas.TransactionCreate, category)`.
- Produces: `GET /api/v1/accounts/{id}/month-check` → `[{month, money_in, money_out, difference, booked}]` newest
  first; `POST /api/v1/accounts/{id}/month-check/{month}` → transaction JSON.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_month_check.py`)

```python
@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    return {"headers": headers, "migros": clearing(client, headers)}


def put(client, mum, category, amount, date):
    response = add_transaction(client, mum["headers"], mum["migros"], category_id(client, category), amount, date=date)
    assert response.status_code == 200, response.text
    return response.json()


def check(client, headers, account):
    return client.get(f"{BASE_URL}/accounts/{account}/month-check", headers=headers)


def book(client, headers, account, month):
    return client.post(f"{BASE_URL}/accounts/{account}/month-check/{month}", headers=headers)


class TestList:
    def test_each_month_on_its_own_bookings(self, client, mum):
        put(client, mum, "Gift", 300, "2025-08-03")
        put(client, mum, "Groceries", 250, "2025-08-04")
        put(client, mum, "Gift", 100, "2025-09-03")
        put(client, mum, "Groceries", 100, "2025-09-04")
        assert check(client, mum["headers"], mum["migros"]).json() == [
            {"month": "2025-08", "money_in": 300.0, "money_out": 250.0, "difference": 50.0, "booked": False}
        ]

    def test_newest_first_both_signs(self, client, mum):
        put(client, mum, "Gift", 10, "2025-07-03")
        put(client, mum, "Gift", 100, "2025-08-03")
        put(client, mum, "Groceries", 112.40, "2025-08-04")
        rows = check(client, mum["headers"], mum["migros"]).json()
        assert [(r["month"], r["difference"]) for r in rows] == [("2025-08", -12.4), ("2025-07", 10.0)]

    def test_swiss_month_boundaries(self, client, mum):
        put(client, mum, "Gift", 50, "2025-08-31T21:30:00Z")  # 23:30 in Zurich: August
        put(client, mum, "Groceries", 50, "2025-08-15")
        put(client, mum, "Gift", 20, "2025-08-31T22:30:00Z")  # 00:30 on 1 September in Zurich
        put(client, mum, "Groceries", 20, "2025-09-10")
        assert check(client, mum["headers"], mum["migros"]).json() == []

    def test_cents_add_up(self, client, mum):
        put(client, mum, "Gift", 0.1, "2025-08-01")
        put(client, mum, "Gift", 0.2, "2025-08-01")
        put(client, mum, "Groceries", 0.3, "2025-08-02")
        assert check(client, mum["headers"], mum["migros"]).json() == []

    def test_current_month_left_out(self, client, mum):
        put(client, mum, "Gift", 20, datetime.now(ZoneInfo("Europe/Zurich")).isoformat())
        assert check(client, mum["headers"], mum["migros"]).json() == []

    def test_only_clearing_accounts(self, client, mum):
        bank = create_account(client, mum["headers"], "Bank")
        response = check(client, mum["headers"], bank)
        assert response.status_code == 400
        assert response.json()["detail"] == "Only clearing accounts have a month check"

    def test_view_share_sees_but_cannot_book(self, client, mum):
        dad = register(client, "dad")
        dads = clearing(client, dad)
        add_transaction(client, dad, dads, category_id(client, "Gift"), 5, date="2025-08-01")
        client.put(f"{BASE_URL}/shares/{user_id(client, dad, 'mum')}", json={"level": "VIEW"}, headers=dad)
        assert check(client, mum["headers"], dads).status_code == 200
        assert book(client, mum["headers"], dads, "2025-08").status_code == 403


class TestBook:
    def test_gap_booked_as_unknown_expense(self, client, mum):
        put(client, mum, "Gift", 300, "2025-08-03")
        put(client, mum, "Groceries", 250, "2025-08-04")
        response = book(client, mum["headers"], mum["migros"], "2025-08")
        assert response.status_code == 200, response.text
        booked = response.json()
        assert booked["category_id"] == category_id(client, "Unknown expense")
        assert booked["amount"] == -50.0
        assert booked["description"] == "Month check August 2025"
        assert booked["reference"] == "month-check:2025-08"
        assert booked["date"].startswith("2025-08-31T12:00")
        assert check(client, mum["headers"], mum["migros"]).json() == []
        assert balance(client, mum["headers"], mum["migros"]) == 0

    def test_receipts_over_booked_as_income(self, client, mum):
        put(client, mum, "Gift", 100, "2025-08-03")
        put(client, mum, "Groceries", 112.40, "2025-08-04")
        booked = book(client, mum["headers"], mum["migros"], "2025-08").json()
        assert booked["category_id"] == category_id(client, "Other Income")
        assert booked["amount"] == 12.4

    def test_booked_once_until_deleted(self, client, mum):
        put(client, mum, "Gift", 300, "2025-08-03")
        put(client, mum, "Groceries", 250, "2025-08-04")
        first = book(client, mum["headers"], mum["migros"], "2025-08").json()
        put(client, mum, "Groceries", 5, "2025-08-05")  # a receipt that turned up later
        assert check(client, mum["headers"], mum["migros"]).json()[0]["booked"] is True
        second = book(client, mum["headers"], mum["migros"], "2025-08")
        assert second.status_code == 409
        client.delete(f"{BASE_URL}/transactions/{first['id']}", headers=mum["headers"])
        assert book(client, mum["headers"], mum["migros"], "2025-08").json()["amount"] == -45.0

    @pytest.mark.parametrize(
        "month, detail",
        [
            ("2025-13", "Month must be YYYY-MM"),
            ("2025-07", "This month adds up already"),
            (datetime.now(ZoneInfo("Europe/Zurich")).strftime("%Y-%m"), "Only completed months can be checked"),
            ("2999-01", "Only completed months can be checked"),
        ],
    )
    def test_errors(self, client, mum, month, detail):
        response = book(client, mum["headers"], mum["migros"], month)
        assert response.status_code == 400
        assert response.json()["detail"] == detail
```

- [ ] **Step 2: Run** the file — Expected: TestList/TestBook fail with 404 (route missing).

- [ ] **Step 3: Implement** `backend/app/month_check.py`

```python
"""Month check for clearing accounts (Migros, ...): money comes in by transfer and goes out by receipts, so each
completed month's own bookings should add up to 0. The gap is booked once as "Unknown expense" (money without
receipts) or "Other Income" (receipts paid partly by gift cards or vouchers)."""

import calendar
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import auth, crud, database, models, privacy, schemas
from .seed import UNKNOWN_EXPENSE

router = APIRouter()

ZURICH = ZoneInfo("Europe/Zurich")
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
GAP_INCOME = "Other Income"


def month_of(value: datetime) -> str:
    """The Swiss calendar month (YYYY-MM) of a stored date (naive UTC)."""
    return value.replace(tzinfo=timezone.utc).astimezone(ZURICH).strftime("%Y-%m")


def reference(month: str) -> str:
    return f"month-check:{month}"


def clearing_account(db: Session, current_user, account_id: str, write: bool = False) -> models.Account:
    account = privacy.check_account_access(db, current_user, account_id, write=write)
    if account.type != models.AccountType.CLEARING:
        raise HTTPException(status_code=400, detail="Only clearing accounts have a month check")
    return account


def months(db: Session, account: models.Account) -> dict:
    """Per Swiss month: money in, money out, their difference, and whether its month-check booking exists."""
    sums = defaultdict(lambda: [0.0, 0.0])
    references = set()
    for t in db.query(models.Transaction).filter(models.Transaction.account_id == account.id):
        sums[month_of(t.date)][0 if t.amount >= 0 else 1] += abs(t.amount)
        references.add(t.reference)
    return {
        month: {
            "month": month,
            "money_in": crud.to_cents(money_in),
            "money_out": crud.to_cents(money_out),
            # Rounded to cents, so float noise counts as 0
            "difference": crud.to_cents(money_in - money_out) + 0.0,
            "booked": reference(month) in references,
        }
        for month, (money_in, money_out) in sums.items()
    }


def current_month() -> str:
    return datetime.now(ZURICH).strftime("%Y-%m")


@router.get("/accounts/{account_id}/month-check")
def get_month_check(
    account_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> List[dict]:
    account = clearing_account(db, current_user, account_id)
    open_months = [m for m in months(db, account).values() if m["month"] < current_month() and m["difference"]]
    return sorted(open_months, key=lambda m: m["month"], reverse=True)


@router.post("/accounts/{account_id}/month-check/{month}", response_model=schemas.Transaction)
def book_month_check(
    account_id: str,
    month: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    account = clearing_account(db, current_user, account_id, write=True)
    if not MONTH.match(month):
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM")
    if month >= current_month():
        raise HTTPException(status_code=400, detail="Only completed months can be checked")
    row = months(db, account).get(month)
    if not row or not row["difference"]:
        raise HTTPException(status_code=400, detail="This month adds up already")
    if row["booked"]:
        raise HTTPException(
            status_code=409, detail="Already booked; delete the month-check booking to book the new difference"
        )
    name = UNKNOWN_EXPENSE if row["difference"] > 0 else GAP_INCOME
    category = db.query(models.Category).filter(models.Category.name == name).one()
    year, number = int(month[:4]), int(month[5:])
    transaction = schemas.TransactionCreate(
        account_id=account.id,
        category_id=category.id,
        amount=abs(row["difference"]),
        description=f"Month check {calendar.month_name[number]} {year}",
        reference=reference(month),
        # Noon UTC on the last day: that day in Switzerland too (same as a date-only import)
        date=datetime(year, number, calendar.monthrange(year, number)[1], 12, tzinfo=timezone.utc),
    )
    return crud.create_transaction(db, transaction, category)
```

  `main.py`: `from . import month_check` with the other routers; `app.include_router(month_check.router,
  prefix="/api/v1")`. If `schemas.TransactionCreate` lacks `reference`/`date`, use what the import uses (check
  `import_api.py`).

- [ ] **Step 4: Run** the file — Expected: all pass. Then the full suite in the background — Expected: all pass.
- [ ] **Step 5: Lint** (`black --check`, `flake8` from `backend/`) and **commit**
  `feat(accounts): month check books a clearing account's monthly gap`

### Task 3: Frontend

**Files:**
- Create: `frontend/src/components/MonthCheck.tsx`
- Modify: `frontend/src/pages/dashboard/Dashboard.tsx` (tab label, two type selects, render MonthCheck)
- Browser test: `scratchpad/e2e/month-check.js` (not in the repo)

**Interfaces:**
- Consumes: the two endpoints of Task 2; `money` from `finance.ts`; `errorMessage` from `api.ts`.
- Produces: `<MonthCheck accounts canBook version onBooked />`.

- [ ] **Step 1: Write the browser test** `month-check.js` (pattern of `transfers.js`): log in as Admin (PIN 1111);
  check the first tab reads "🏦 Accounts"; create account "Migros" with type Clearing in the form; via the API
  (fetch with the page's token) book Gift 300 and Groceries 250 on 2025-08-03/04; reload; expect the text
  "August 2025" and a button "Book as Unknown expense"; click it; expect "All months add up."; open the Analytics
  tab with a period covering August 2025 or check via the API that the Unknown expense booking exists; count
  `/month-check` requests over 3 s idle to be ≤ 2 (no render loop).
- [ ] **Step 2: Run it** against the current frontend — Expected: fails on the tab label.
- [ ] **Step 3: Implement** `MonthCheck.tsx`

```tsx
import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import { money } from '../finance';

interface Account { id: string; name: string }
interface Month { month: string; money_in: number; money_out: number; difference: number; booked: boolean }

const monthName = (month: string) =>
    new Date(`${month}-15T12:00:00`).toLocaleDateString('en', { month: 'long', year: 'numeric' });

// Clearing accounts (Migros, ...) should add up to 0 every month: money in by transfer, out by receipts.
// The gap is booked once per month: "Unknown expense", or "Other Income" when the receipts exceed the money.
export default function MonthCheck({ accounts, canBook, version, onBooked }: {
    accounts: Account[];
    canBook: (account: Account) => boolean;
    version: number;
    onBooked: () => void;
}) {
    const [months, setMonths] = useState<Record<string, Month[]>>({});
    const [error, setError] = useState('');
    // The parent passes a freshly filtered list on every render; reload only when the accounts really change
    const ids = accounts.map(a => a.id).join(',');

    useEffect(() => {
        if (!ids) return;
        Promise.all(ids.split(',').map(id =>
            api.get(`/api/v1/accounts/${id}/month-check`).then(r => [id, r.data as Month[]] as const)))
            .then(entries => setMonths(Object.fromEntries(entries)))
            .catch(err => setError(errorMessage(err, 'Failed to load the month check')));
    }, [ids, version]);

    if (!accounts.length) return null;

    const book = async (account: Account, month: Month) => {
        try {
            await api.post(`/api/v1/accounts/${account.id}/month-check/${month.month}`);
            setError('');
            onBooked();
        } catch (err) {
            setError(errorMessage(err, 'Failed to book the month check'));
        }
    };

    return (
        <div className="glass-card p-6">
            <h2 className="text-xl font-bold mb-1">Month check</h2>
            <p className="text-sm text-slate-400 mb-4">
                Clearing accounts should end every month at 0. What's left is booked once: money without receipts as
                "Unknown expense", receipts paid by gift card or vouchers as "Other Income".
            </p>
            {error && <p className="text-red-400 text-sm mb-2">{error}</p>}
            {accounts.map(account => {
                const open = months[account.id] ?? [];
                return (
                    <div key={account.id} className="mb-4">
                        <h3 className="font-semibold">{account.name}</h3>
                        {open.length === 0 ? (
                            <p className="text-sm text-emerald-400">All months add up.</p>
                        ) : (
                            <ul className="space-y-2 mt-2">
                                {open.map(m => (
                                    <li key={m.month} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm p-2 rounded bg-slate-800/30">
                                        <span className="font-medium w-36">{monthName(m.month)}</span>
                                        <span className="text-slate-400">in {money(m.money_in)}</span>
                                        <span className="text-slate-400">out {money(m.money_out)}</span>
                                        <span>{m.difference > 0
                                            ? `not tracked ${money(m.difference)}`
                                            : `receipts over ${money(-m.difference)}`}</span>
                                        {m.booked ? (
                                            <span className="text-amber-400">Already booked; delete the month-check booking to book the new difference</span>
                                        ) : canBook(account) && (
                                            <button onClick={() => book(account, m)} className="btn-primary text-xs">
                                                {m.difference > 0 ? 'Book as Unknown expense' : 'Book as Other Income'}
                                            </button>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
```

  `Dashboard.tsx`: tab `{ id: 'overview', label: '🏦 Accounts' }`; after `<option value="SAVINGS">Savings</option>`
  in both selects add `<option value="CLEARING">Clearing (Migros, …)</option>`; after the Accounts section card add
  `<MonthCheck accounts={accounts.filter(a => a.type === 'CLEARING')} canBook={canEdit} version={dataVersion}
  onBooked={refresh} />` (ensure the `Account` interface has `type: string`).
- [ ] **Step 4:** `npm run lint`, `npm run type-check`, `npm run build`; restart backend (`restart-backend.sh`),
  `npx vite --port 3000`; run `month-check.js` and `transfers.js` — Expected: all OK.
- [ ] **Step 5: Commit** `feat(frontend): Accounts tab with the month check, account type Clearing`

### Task 4: Docs and issue

**Files:** `tools/converters/README.md`, `tools/converters/converter.example.toml`,
`docs/superpowers/specs/2026-10-14-bank-and-migros-converters-design.md`

- [ ] README set-up step 1: create "Migros" with type **Clearing**; Migros section: replace "book it by hand on the
  Migros account" with the month check on the Accounts tab.
- [ ] Example config: `account = "Migros"` comment → `# account of type Clearing: transfers in, receipts out`.
- [ ] Converters spec: the #21 references (decisions list, totals check, out of scope) → "the month check
  (`2026-10-15-budget-and-accounts-design.md`)".
- [ ] Commit `docs: clearing accounts and the month check in the converter docs`.
- [ ] Close #21: `gh issue close 21 -R FrankAndreas/family-budget-dashboard -c "Replaced by the month check on
  clearing accounts (spec docs/superpowers/specs/2026-10-15-budget-and-accounts-design.md)."` — after the branch is
  merged or the PR opened; mention it in the final report.
