# Separate Parent Finances, Common Budget, Investments and Yearly Bills — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each parent private finances (shareable as view or edit), add a common budget with preset splits, who-owes-whom and monthly shares, and add Investments and Yearly bills tabs.

**Architecture:** Backend: access rules move from "parents share a household" to per-parent shares in `privacy.py`; new tables for shares, splits, settlements, planned costs and assets; pure calculations in a new `finance.py`; new routes in a new `common_api.py` router so `api.py` doesn't keep growing. Frontend: scopes become "me / shared parents / allowance children"; three new tab components plus a share setting; the expense form gets "Shared" and "For item".

**Tech Stack:** FastAPI, SQLAlchemy 2 (SQLite), Pydantic 2, pytest; React 19, TypeScript, Vite 8, Tailwind 4, axios.

**Spec:** `docs/superpowers/specs/2026-10-14-separate-finances-design.md`

## Global Constraints

- All money values rounded to cents with `crud.to_cents` (stored as Float).
- PINs stay exactly 4 digits; no change to login.
- No Alembic: new tables come from `create_all`, new columns are added to `migrate.NEW_COLUMNS`.
- At most 4 splits; split percents are whole numbers ≥ 0 summing to 100, one entry per active parent.
- Shared expenses count in full in the payer's budgets and analytics; `TRANSFER` transactions count in neither.
- Children (allowance or dependent) never see the Common, Investments and Yearly bills tabs; their existing rules are unchanged, except that a parent can no longer write on a child's account (read-only, as the spec says "never edit").
- Python formatted with black (line length from `pyproject.toml`), flake8 clean; frontend `npm run lint` and `npm run type-check` clean.
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01RaCTcgMWXy4Us8UHLhGGcH
  ```

## Commands

- Backend tests: `$S/venv/bin/python -m pytest tests -q` from the repo root, where
  `S=/tmp/claude-1000/-home-andreas-work-family-budget-dashboard/bddd66bf-d388-43ab-9697-f451f8c8ad58/scratchpad`
  (any Python 3.14 venv with `backend/requirements.txt`, pytest and httpx works).
- Lint backend: `$S/venv/bin/black --check backend tests && $S/venv/bin/flake8 backend tests`
- Frontend: `cd frontend && npm run lint && npm run type-check && npm run build`

## Review Focus

1. **A split edited after expenses were booked** — past who-owes-whom must not change (snapshot in `split_shares`). Test in Task 4.
2. **A third parent added after splits exist** — calculations treat the missing percent as 0 and the split can be edited to include them; nothing crashes. Test in Task 3 and Task 4.
3. **Yearly bill due in the current month, and in January seen from December** — "next due" is this month (not next year) and crosses the year boundary correctly. Test in Task 2.
4. **Editing a shared expense into income, or moving it to a child's account category** — rejected, so no income is ever "shared". Test in Task 4.
5. **Deleting a parent who has shares, settlements, planned costs and assets** — no orphan rows break the Common tab afterwards. Test in Task 7.

---

### Task 1: Per-parent access and sharing (backend)

Parents stop seeing each other's money unless shared. Budgets belong to one person. Accounts and budgets can be created on behalf of a parent who granted EDIT.

**Files:**
- Modify: `backend/app/models.py` (add `ShareLevel`, `Share`)
- Modify: `backend/app/privacy.py` (rewrite)
- Modify: `backend/app/schemas.py` (add `ShareSet`, `Share`; `user_id` on `AccountCreate`, `BudgetCreate`)
- Modify: `backend/app/api.py` (accounts, transactions, budgets, users list, shares routes)
- Modify: `backend/app/crud.py` (`delete_user` removes shares)
- Create: `tests/test_shares.py`
- Modify: `tests/test_family.py` (household tests)

**Interfaces:**
- Produces: `privacy.access_level(db, current_user, target_user) -> Optional[str]` returning `"OWN" | "EDIT" | "VIEW" | None`;
  `privacy.check_account_access(db, current_user, account_id, write=False) -> models.Account`;
  `privacy.check_user_access(db, current_user, target_user_id, write=False) -> models.User`;
  `privacy.active_parents(db) -> list[models.User]`;
  `GET /api/v1/shares -> [{"owner_id","grantee_id","level"}]`; `PUT /api/v1/shares/{grantee_id}` body `{"level": "NONE"|"VIEW"|"EDIT"}`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_shares.py`:

```python
"""Parents' finances are private unless shared with the other parent (view or edit)."""

import pytest

from helpers import BASE_URL, add_transaction, category_id, create_account, register, user_id


@pytest.fixture
def parents(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    return {
        "mum": mum,
        "dad": dad,
        "mum_id": user_id(client, mum, "mum"),
        "dad_id": user_id(client, mum, "dad"),
        "mum_account": create_account(client, mum, "Mum bank"),
        "dad_account": create_account(client, dad, "Dad bank"),
    }


def share(client, headers, grantee_id, level):
    return client.put(f"{BASE_URL}/shares/{grantee_id}", json={"level": level}, headers=headers)


def account_names(client, headers):
    return sorted(a["name"] for a in client.get(f"{BASE_URL}/accounts", headers=headers).json())


def test_parents_private_by_default(client, parents):
    assert account_names(client, parents["mum"]) == ["Mum bank"]
    response = client.get(f"{BASE_URL}/accounts/{parents['dad_account']}/transactions", headers=parents["mum"])
    assert response.status_code == 403
    # Still listed as family members (needed for splits and the share setting)
    names = {u["username"] for u in client.get(f"{BASE_URL}/users", headers=parents["mum"]).json()}
    assert {"Admin", "mum", "dad"} <= names


def test_view_share_is_read_only(client, parents):
    assert share(client, parents["dad"], parents["mum_id"], "VIEW").status_code == 200
    assert account_names(client, parents["mum"]) == ["Dad bank", "Mum bank"]
    groceries = category_id(client, "Groceries")
    assert add_transaction(client, parents["mum"], parents["dad_account"], groceries, 10).status_code == 403
    renamed = client.put(f"{BASE_URL}/accounts/{parents['dad_account']}", json={"name": "x"}, headers=parents["mum"])
    assert renamed.status_code == 403
    budgets = client.get(f"{BASE_URL}/budgets", params={"user_id": parents["dad_id"]}, headers=parents["mum"])
    assert budgets.status_code == 200
    on_behalf = client.post(
        f"{BASE_URL}/budgets",
        json={"category_id": groceries, "limit": 100, "user_id": parents["dad_id"]},
        headers=parents["mum"],
    )
    assert on_behalf.status_code == 403


def test_edit_share_delegates(client, parents):
    share(client, parents["dad"], parents["mum_id"], "EDIT")
    groceries = category_id(client, "Groceries")
    expense = add_transaction(client, parents["mum"], parents["dad_account"], groceries, 10)
    assert expense.status_code == 200
    assert client.delete(f"{BASE_URL}/transactions/{expense.json()['id']}", headers=parents["mum"]).status_code == 200

    account = client.post(
        f"{BASE_URL}/accounts",
        json={"name": "Dad cash", "type": "CASH", "user_id": parents["dad_id"]},
        headers=parents["mum"],
    )
    assert account.status_code == 200 and account.json()["user_id"] == parents["dad_id"]
    budget = client.post(
        f"{BASE_URL}/budgets",
        json={"category_id": groceries, "limit": 100, "user_id": parents["dad_id"]},
        headers=parents["mum"],
    )
    assert budget.status_code == 200 and budget.json()["user_id"] == parents["dad_id"]
    assert client.delete(f"{BASE_URL}/budgets/{budget.json()['id']}", headers=parents["mum"]).status_code == 200


def test_share_can_be_revoked(client, parents):
    share(client, parents["dad"], parents["mum_id"], "EDIT")
    assert share(client, parents["dad"], parents["mum_id"], "NONE").status_code == 200
    assert account_names(client, parents["mum"]) == ["Mum bank"]
    assert client.get(f"{BASE_URL}/shares", headers=parents["mum"]).json() == []


def test_shares_listed_for_both_parents(client, parents):
    share(client, parents["dad"], parents["mum_id"], "VIEW")
    expected = [{"owner_id": parents["dad_id"], "grantee_id": parents["mum_id"], "level": "VIEW"}]
    assert client.get(f"{BASE_URL}/shares", headers=parents["mum"]).json() == expected
    assert client.get(f"{BASE_URL}/shares", headers=parents["dad"]).json() == expected


def test_share_only_between_parents(client, parents):
    teen = register(client, "teen", role="CHILD")
    teen_id = user_id(client, parents["mum"], "teen")
    assert share(client, parents["mum"], teen_id, "VIEW").status_code == 400
    assert share(client, parents["mum"], parents["mum_id"], "VIEW").status_code == 400
    assert share(client, teen, parents["mum_id"], "VIEW").status_code == 403
    assert share(client, parents["mum"], parents["dad_id"], "ALL").status_code == 422


def test_budgets_belong_to_one_parent(client, parents):
    groceries = category_id(client, "Groceries")
    mine = client.post(f"{BASE_URL}/budgets", json={"category_id": groceries, "limit": 50}, headers=parents["mum"])
    assert client.get(f"{BASE_URL}/budgets", headers=parents["dad"]).json() == []
    assert client.delete(f"{BASE_URL}/budgets/{mine.json()['id']}", headers=parents["dad"]).status_code == 404
    assert client.delete(f"{BASE_URL}/budgets/{mine.json()['id']}", headers=parents["mum"]).status_code == 200


def test_parent_reads_but_does_not_write_child_account(client, parents):
    teen = register(client, "teen", role="CHILD")
    teen_account = create_account(client, teen, "Teen bank")
    groceries = category_id(client, "Groceries")
    assert add_transaction(client, parents["mum"], teen_account, groceries, 5).status_code == 403
    assert client.get(f"{BASE_URL}/accounts/{teen_account}/transactions", headers=parents["mum"]).status_code == 200


def test_deleting_parent_removes_their_shares(client, parents):
    share(client, parents["dad"], parents["mum_id"], "VIEW")
    client.delete(f"{BASE_URL}/users/{parents['dad_id']}", headers=parents["mum"])
    assert client.get(f"{BASE_URL}/shares", headers=parents["mum"]).json() == []
```

- [ ] **Step 2: Update `tests/test_family.py` for the removed household**

Replace the module docstring's first line with
`"""Family model: private parent finances, children with own allowance, dependent children tagged on expenses."""`.

Replace `test_parents_share_household` with:

```python
def test_parents_are_private(client, family):
    names = sorted(a["name"] for a in client.get(f"{BASE_URL}/accounts", headers=family["mum"]).json())
    assert names == ["Mum bank", "Teen bank"]
    assert (
        add_transaction(client, family["mum"], family["dad_account"], category_id(client, "Groceries"), 10).status_code
        == 403
    )
```

In `test_tagging_rules`, the second rejected case books on the teen's account as Mum, which is now 403 before
the tag is checked. Book it as the teen instead (their own account; the tag is still refused with 400):
replace `client, family["mum"], family["teen_account"], clothing, 5, member_id=family["timmy_id"]` with
`client, family["teen"], family["teen_account"], clothing, 5, member_id=family["timmy_id"]`.

Replace `test_household_and_child_budgets` with:

```python
def test_parent_and_child_budgets(client, family):
    groceries, clothing = category_id(client, "Groceries"), category_id(client, "Clothing")
    mums = client.post(f"{BASE_URL}/budgets", json={"category_id": groceries, "limit": 400}, headers=family["mum"]).json()
    own = client.post(f"{BASE_URL}/budgets", json={"category_id": clothing, "limit": 50}, headers=family["teen"]).json()

    assert client.get(f"{BASE_URL}/budgets", headers=family["dad"]).json() == []
    assert [b["id"] for b in client.get(f"{BASE_URL}/budgets", headers=family["mum"]).json()] == [mums["id"]]
    assert [b["id"] for b in client.get(f"{BASE_URL}/budgets", headers=family["teen"]).json()] == [own["id"]]
    inspected = client.get(f"{BASE_URL}/budgets", params={"user_id": family["teen_id"]}, headers=family["mum"]).json()
    assert [b["id"] for b in inspected] == [own["id"]]

    mum_id = user_id(client, family["mum"], "mum")
    assert client.get(f"{BASE_URL}/budgets", params={"user_id": mum_id}, headers=family["teen"]).status_code == 403
    # Parents only inspect a child's budgets, and don't touch each other's without a share
    assert client.delete(f"{BASE_URL}/budgets/{own['id']}", headers=family["mum"]).status_code == 404
    assert client.delete(f"{BASE_URL}/budgets/{mums['id']}", headers=family["dad"]).status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$S/venv/bin/python -m pytest tests/test_shares.py tests/test_family.py -q`
Expected: FAIL (404 on `/shares`, parents still see each other's accounts).

- [ ] **Step 4: Add the model** — in `backend/app/models.py`, after `CategoryType`:

```python
class ShareLevel(str, enum.Enum):
    VIEW = "VIEW"
    EDIT = "EDIT"
```

and at the end of the file:

```python
class Share(Base):
    """A parent shares their own finances with another parent: read only (VIEW) or managing them (EDIT)."""

    __tablename__ = "shares"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(String, ForeignKey("users.id"))
    grantee_id = Column(String, ForeignKey("users.id"))
    level = Column(Enum(ShareLevel))
```

- [ ] **Step 5: Rewrite `backend/app/privacy.py`**

```python
from typing import Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from . import models

# Access rules:
# - Everyone has full access to their own money ("OWN")
# - A parent's money is private; another parent gets "VIEW" or "EDIT" only if it was shared with them
# - Parents view a child with own allowance unless the child turned on privacy (read only)
# - Children only see themselves
# The family list itself (names, roles) is visible to all parents.


def share_level(db: Session, owner_id: str, grantee_id: str) -> Optional[str]:
    share = (
        db.query(models.Share)
        .filter(models.Share.owner_id == owner_id, models.Share.grantee_id == grantee_id)
        .first()
    )
    return share.level.value if share else None


def access_level(db: Session, current_user: models.User, target_user: models.User) -> Optional[str]:
    if target_user.id == current_user.id:
        return "OWN"
    if current_user.role != models.UserRole.PARENT:
        return None
    if target_user.role == models.UserRole.PARENT:
        return share_level(db, target_user.id, current_user.id)
    return None if target_user.privacy_enabled else "VIEW"


def can_write(level: Optional[str]) -> bool:
    return level in ("OWN", "EDIT")


def check_user_access(db: Session, current_user: models.User, target_user_id: str, write: bool = False) -> models.User:
    """The target user if the current user may view (or with write=True, manage) their money; 403/404 otherwise."""
    target_user = db.query(models.User).filter(models.User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    level = access_level(db, current_user, target_user)
    if level is None or (write and not can_write(level)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to access this user's data"
        )
    return target_user


def check_account_access(db: Session, current_user: models.User, account_id: str, write: bool = False) -> models.Account:
    """The account if the current user may view (or with write=True, change) it; 403/404 otherwise."""
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    owner = db.query(models.User).filter(models.User.id == account.user_id).first()
    level = access_level(db, current_user, owner) if owner else None
    if level is None or (write and not can_write(level)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to access this account"
        )
    return account


def get_accessible_accounts(db: Session, current_user: models.User) -> list[models.Account]:
    users = db.query(models.User).all()
    user_ids = [user.id for user in users if access_level(db, current_user, user) is not None]
    return db.query(models.Account).filter(models.Account.user_id.in_(user_ids)).all()


def can_list_user(current_user: models.User, target_user: models.User) -> bool:
    """Who appears in the family list: parents see everyone except children with privacy on."""
    if target_user.id == current_user.id:
        return True
    if current_user.role != models.UserRole.PARENT:
        return False
    return target_user.role == models.UserRole.PARENT or not target_user.privacy_enabled


def active_parents(db: Session) -> list[models.User]:
    return (
        db.query(models.User)
        .filter(models.User.role == models.UserRole.PARENT, models.User.is_active.is_(True))
        .all()
    )
```

- [ ] **Step 6: Schemas** — in `backend/app/schemas.py`: change the import line to
`from .models import UserRole, AccountType, CategoryType, ShareLevel`, then

replace `class AccountCreate(AccountBase): pass` with:

```python
class AccountCreate(AccountBase):
    # Set to create the account for a parent who shared their finances with EDIT
    user_id: Optional[str] = None
```

in `BudgetCreate` add the field `user_id: Optional[str] = None` (same comment), and at the end add:

```python
# Share Schemas
class ShareSet(BaseModel):
    level: Literal["NONE", "VIEW", "EDIT"]


class Share(BaseModel):
    owner_id: str
    grantee_id: str
    level: ShareLevel

    class Config:
        from_attributes = True
```

- [ ] **Step 7: Routes** — in `backend/app/api.py`:

`read_users`: replace the two lines computing `accessible_users` with
`return [user for user in db.query(crud.models.User).all() if privacy.can_list_user(current_user, user)]`.

`create_account`: replace the body after the dependent check with:

```python
    owner_id = account.user_id or current_user.id
    privacy.check_user_access(db, current_user, owner_id, write=True)
    return crud.create_account(db, account=account, user_id=owner_id)
```

`get_own_account`: replace the body with:

```python
    # The owner, or a parent they shared their finances with as EDIT
    return privacy.check_account_access(db, current_user, account_id, write=True)
```

`create_transaction`, `update_transaction`, `delete_transaction`: pass `write=True` to `privacy.check_account_access`.

Replace `budget_owner_ids`, `get_budgets`, `create_budget` and `get_manageable_budget` with:

```python
@router.get("/budgets", response_model=List[schemas.Budget])
def get_budgets(
    user_id: Optional[str] = None,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Without user_id: the caller's own budgets. With user_id: someone else's they may view.
    owner = privacy.check_user_access(db, current_user, user_id) if user_id else current_user
    return crud.get_budgets(db, owner.id)


@router.post("/budgets", response_model=schemas.Budget)
def create_budget(
    budget: schemas.BudgetCreate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    owner = privacy.check_user_access(db, current_user, budget.user_id, write=True) if budget.user_id else current_user
    if is_dependent(owner):
        raise HTTPException(status_code=403, detail="Children without own allowance can't have budgets")
    if not crud.get_category(db, budget.category_id):
        raise HTTPException(status_code=400, detail="Category not found")
    return crud.create_budget(db, budget=budget, user_id=owner.id)


def get_manageable_budget(db: Session, current_user, budget_id: str):
    db_budget = crud.get_budget(db, budget_id)
    owner = db.query(models.User).filter(models.User.id == db_budget.user_id).first() if db_budget else None
    # Own budgets, or those of a parent who shared with EDIT
    if not owner or not privacy.can_write(privacy.access_level(db, current_user, owner)):
        raise HTTPException(status_code=404, detail="Budget not found")
    return db_budget
```

Append the share routes:

```python
# Share Routes
@router.get("/shares", response_model=List[schemas.Share])
def get_shares(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    # What the current user shared, and what was shared with them
    return (
        db.query(models.Share)
        .filter((models.Share.owner_id == current_user.id) | (models.Share.grantee_id == current_user.id))
        .all()
    )


@router.put("/shares/{grantee_id}")
def set_share(
    grantee_id: str,
    share: schemas.ShareSet,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if current_user.role != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can share their finances")
    grantee = db.query(models.User).filter(models.User.id == grantee_id).first()
    if not grantee or grantee.role != "PARENT" or grantee.id == current_user.id:
        raise HTTPException(status_code=400, detail="You can only share with the other parent")
    crud.set_share(db, current_user.id, grantee_id, share.level)
    return {"level": share.level}
```

- [ ] **Step 8: CRUD** — in `backend/app/crud.py` add after `delete_user`:

```python
def set_share(db: Session, owner_id: str, grantee_id: str, level: str):
    db.query(models.Share).filter(models.Share.owner_id == owner_id, models.Share.grantee_id == grantee_id).delete(
        synchronize_session=False
    )
    if level != "NONE":
        db.add(models.Share(owner_id=owner_id, grantee_id=grantee_id, level=level))
    db.commit()
```

and in `delete_user`, before `db.delete(db_user)`:

```python
    db.query(models.Share).filter((models.Share.owner_id == user_id) | (models.Share.grantee_id == user_id)).delete(
        synchronize_session=False
    )
```

Delete `get_budgets_for_users` from `crud.py` (no longer used).

- [ ] **Step 9: Run all backend tests**

Run: `$S/venv/bin/python -m pytest tests -q`
Expected: PASS. If `tests/test_api.py` privacy tests fail because a parent wrote on a child's account, change that assertion to expect 403 (spec: parents never edit a child's money).

- [ ] **Step 10: Lint and commit**

```bash
$S/venv/bin/black backend tests && $S/venv/bin/flake8 backend tests
git add backend tests
git commit -m "feat(access): private parent finances, shareable as view or edit"
```

---

### Task 2: Transfer category and calculation module

**Files:**
- Modify: `backend/app/models.py` (`CategoryType.TRANSFER`)
- Modify: `backend/app/seed.py` (seed missing default categories by name, add "Settle up")
- Modify: `backend/app/crud.py` (`signed_amount` handles TRANSFER)
- Create: `backend/app/finance.py`
- Create: `tests/test_finance.py`
- Modify: `tests/test_review_fixes.py:24` (15 → 16 categories)

**Interfaces:**
- Produces (all pure, no DB):
  - `finance.monthly_equivalent(amount: float, frequency: str) -> float`
  - `finance.next_due(due_month: int, today: date) -> date`
  - `finance.is_due_soon(due: date, today: date) -> bool`
  - `finance.split_amount(amount: float, shares: dict[str, int]) -> dict[str, float]`
  - `finance.balances(expenses: list[tuple[str, float, dict[str, int]]], settlements: list[tuple[str, str, float]]) -> dict[str, float]` (positive = is owed money)
  - `finance.asset_stats(price: float, purchase_date: date, lifespan_years: int, follow_up_costs: float, today: date) -> dict` with keys `age_years`, `replacement_due` (date), `is_due` (bool), `monthly_set_aside`, `total_cost`, `cost_per_year`
  - `seed.SETTLE_UP = "Settle up"`

- [ ] **Step 1: Write the failing tests** — create `tests/test_finance.py`:

```python
"""Pure calculations for the common budget, yearly bills and investments."""

from datetime import date

from app import finance


def test_monthly_equivalent():
    assert finance.monthly_equivalent(1200, "YEARLY") == 100
    assert finance.monthly_equivalent(100, "YEARLY") == 8.33
    assert finance.monthly_equivalent(55.5, "MONTHLY") == 55.5


def test_next_due_this_month_later_and_next_year():
    today = date(2026, 10, 14)
    assert finance.next_due(10, today) == date(2026, 10, 1)
    assert finance.next_due(12, today) == date(2026, 12, 1)
    assert finance.next_due(1, today) == date(2027, 1, 1)
    assert finance.next_due(1, date(2026, 12, 31)) == date(2027, 1, 1)


def test_due_soon_is_within_two_months():
    today = date(2026, 11, 20)
    assert finance.is_due_soon(date(2026, 11, 1), today)
    assert finance.is_due_soon(date(2027, 1, 1), today)
    assert not finance.is_due_soon(date(2027, 2, 1), today)


def test_split_amount_rounds_and_covers_total():
    assert finance.split_amount(100, {"a": 70, "b": 30}) == {"a": 70.0, "b": 30.0}
    parts = finance.split_amount(10, {"a": 33, "b": 33, "c": 34})
    assert parts == {"a": 3.3, "b": 3.3, "c": 3.4}


def test_balances_two_parents():
    # Mum paid 100 at 50/50, Dad paid 40 at 70/30 (Mum 70)
    expenses = [("mum", 100, {"mum": 50, "dad": 50}), ("dad", 40, {"mum": 70, "dad": 30})]
    assert finance.balances(expenses, []) == {"mum": 22.0, "dad": -22.0}
    # Dad settles 22
    assert finance.balances(expenses, [("dad", "mum", 22)]) == {"mum": 0.0, "dad": 0.0}


def test_balances_missing_parent_counts_as_zero():
    # A third parent added after the split was made isn't in its shares
    assert finance.balances([("mum", 90, {"mum": 50, "dad": 50})], []) == {"mum": 45.0, "dad": -45.0}


def test_asset_stats():
    stats = finance.asset_stats(2400, date(2022, 10, 14), 8, 300, date(2026, 10, 14))
    assert stats["age_years"] == 4.0
    assert stats["replacement_due"] == date(2030, 10, 14)
    assert stats["is_due"] is False
    assert stats["monthly_set_aside"] == 25.0
    assert stats["total_cost"] == 2700
    assert stats["cost_per_year"] == 675.0


def test_asset_stats_new_and_leap_day():
    stats = finance.asset_stats(1000, date(2024, 2, 29), 1, 0, date(2024, 6, 1))
    assert stats["replacement_due"] == date(2025, 2, 28)
    # Less than a year old: cost per year is the total so far
    assert stats["cost_per_year"] == 1000
    assert finance.asset_stats(1000, date(2020, 1, 1), 3, 0, date(2026, 1, 1))["is_due"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `$S/venv/bin/python -m pytest tests/test_finance.py -q`
Expected: FAIL with `ImportError: cannot import name 'finance'`.

- [ ] **Step 3: Implement `backend/app/finance.py`**

```python
"""Calculations for the common budget, yearly bills and investments. Pure functions, no database."""

from datetime import date


def cents(value: float) -> float:
    return round(value, 2)


def monthly_equivalent(amount: float, frequency: str) -> float:
    return cents(amount / 12 if frequency == "YEARLY" else amount)


def next_due(due_month: int, today: date) -> date:
    """First day of the coming due month; the current month counts as coming."""
    year = today.year if due_month >= today.month else today.year + 1
    return date(year, due_month, 1)


def is_due_soon(due: date, today: date) -> bool:
    """Due in this month or the next two."""
    months_ahead = (due.year - today.year) * 12 + due.month - today.month
    return 0 <= months_ahead <= 2


def split_amount(amount: float, shares: dict[str, int]) -> dict[str, float]:
    return {user_id: cents(amount * percent / 100) for user_id, percent in shares.items()}


def balances(
    expenses: list[tuple[str, float, dict[str, int]]], settlements: list[tuple[str, str, float]]
) -> dict[str, float]:
    """Net position per parent: positive = the others owe them, negative = they owe.

    expenses: (payer_id, amount paid, split percents per parent); settlements: (from_id, to_id, amount).
    A parent missing from a split's percents has a share of 0.
    """
    net: dict[str, float] = {}
    for payer, amount, shares in expenses:
        net.setdefault(payer, 0.0)
        for user_id, share in split_amount(amount, shares).items():
            if user_id == payer:
                continue
            net[payer] += share
            net[user_id] = net.get(user_id, 0.0) - share
    for from_id, to_id, amount in settlements:
        net[from_id] = net.get(from_id, 0.0) + amount
        net[to_id] = net.get(to_id, 0.0) - amount
    return {user_id: cents(value) + 0.0 for user_id, value in net.items()}


def add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February in a non-leap year
        return day.replace(year=day.year + years, day=28)


def asset_stats(price: float, purchase_date: date, lifespan_years: int, follow_up_costs: float, today: date) -> dict:
    age_years = round((today - purchase_date).days / 365.25, 1)
    replacement_due = add_years(purchase_date, lifespan_years)
    total_cost = cents(price + follow_up_costs)
    return {
        "age_years": age_years,
        "replacement_due": replacement_due,
        "is_due": today >= replacement_due,
        "monthly_set_aside": cents(price / (lifespan_years * 12)),
        "total_cost": total_cost,
        "cost_per_year": cents(total_cost / max(age_years, 1)),
    }
```

(`+ 0.0` turns `-0.0` into `0.0` so a settled balance compares equal to `0.0` and prints without a minus.)

- [ ] **Step 4: Run to verify pass**

Run: `$S/venv/bin/python -m pytest tests/test_finance.py -q` — Expected: PASS.

- [ ] **Step 5: Transfer category** — in `models.py` add `TRANSFER = "TRANSFER"` to `CategoryType` with the comment
`# Money moved between parents (settling up): changes balances, counts in neither income nor expenses`.

In `seed.py`: add `SETTLE_UP = "Settle up"` above `DEFAULT_CATEGORIES`, append
`{"name": SETTLE_UP, "type": "TRANSFER", "icon": "🔁"},` to the list, and replace `seed_categories` with:

```python
def seed_categories(db: Session) -> int:
    """Create the default categories that don't exist yet (by name). Returns how many were created."""
    existing = {name for (name,) in db.query(models.Category.name)}
    missing = [cat for cat in DEFAULT_CATEGORIES if cat["name"] not in existing]
    for cat_data in missing:
        db.add(models.Category(**cat_data, is_global=True))
    db.commit()
    return len(missing)
```

In `crud.signed_amount`, keep the sign the caller gives for transfers (settling up books one negative and one positive):

```python
def signed_amount(amount: float, category: models.Category) -> float:
    # The category decides the sign: income is positive, expenses are negative; transfers keep their sign
    if category.type == models.CategoryType.TRANSFER:
        return to_cents(amount)
    if category.type == models.CategoryType.INCOME:
        return to_cents(abs(amount))
    return to_cents(-abs(amount))
```

In `api.create_transaction` and `api.update_transaction`, right after the "Category not found" check, add:

```python
    if category.type == models.CategoryType.TRANSFER:
        raise HTTPException(status_code=400, detail="Transfers are booked with Settle up")
```

(`init_db.py` keeps calling `seed_categories`; its "already exist" message still fits.)

Change `tests/test_review_fixes.py` `test_categories_seeded` to `== 16`, and add to it:

```python
        transfer = category_id(client, "Settle up")
        headers = register(client, "p")
        account = create_account(client, headers)
        assert add_transaction(client, headers, account, transfer, 5).status_code == 400
```

(import `add_transaction`, `category_id`, `create_account`, `register` from `helpers` if not imported yet).

- [ ] **Step 6: Test existing databases get the new category** — add to `tests/test_finance.py`:

```python
def test_seed_adds_missing_categories_to_existing_database():
    from app import database, models
    from app.seed import SETTLE_UP, seed_categories

    with database.SessionLocal() as db:
        db.query(models.Category).filter(models.Category.name == SETTLE_UP).delete()
        db.commit()
        assert seed_categories(db) == 1
        assert seed_categories(db) == 0
```

- [ ] **Step 7: Run all tests, lint, commit**

```bash
$S/venv/bin/python -m pytest tests -q
$S/venv/bin/black backend tests && $S/venv/bin/flake8 backend tests
git add backend tests
git commit -m "feat(finance): calculation module and transfer category for settling up"
```

---

### Task 3: Splits

**Files:**
- Modify: `backend/app/models.py` (`Split`)
- Modify: `backend/app/schemas.py` (`SplitIn`, `Split`)
- Create: `backend/app/common_api.py` (router; splits routes now, more in later tasks)
- Modify: `backend/app/main.py` (include router)
- Create: `tests/test_common.py`

**Interfaces:**
- Consumes: `privacy.active_parents(db)` (Task 1).
- Produces: `models.Split(id, name, shares: dict[str, int])`; `common_api.router`; `common_api.require_parent(current_user)`;
  `common_api.get_split(db, split_id) -> models.Split` (400 "Split not found");
  routes `GET/POST /api/v1/splits`, `PUT/DELETE /api/v1/splits/{id}`; `MAX_SPLITS = 4`.
- Test helpers added to `tests/helpers.py`: `create_split(client, headers, name, shares) -> Response`.

- [ ] **Step 1: Helpers** — in `tests/helpers.py`, let `register` add the member as another parent (the
common-budget tests deactivate "Admin" so that exactly two parents remain):

```python
def register(client, username, role="PARENT", pin="1234", by=None):
    """Have a parent (default: the admin) add a family member, then log in as them."""
    client.post(
        f"{BASE_URL}/users",
        json={"username": username, "pin": pin, "role": role},
        headers=by or admin_headers(client),
    )
    return login(client, username, pin)
```

and append:

```python
def create_split(client, headers, name, shares):
    """shares: {user_id: percent}"""
    return client.post(f"{BASE_URL}/splits", json={"name": name, "shares": shares}, headers=headers)
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_common.py`:

```python
"""Common budget: splits, shared expenses, who owes whom, settling up, monthly overview."""

import pytest

from helpers import BASE_URL, create_split, register, user_id


@pytest.fixture
def parents(client):
    # The test database starts with the parent "Admin"; deactivate it so mum and dad are the two parents
    mum = register(client, "mum")
    dad = register(client, "dad")
    admin_id = user_id(client, mum, "Admin")
    client.put(f"{BASE_URL}/users/{admin_id}", json={"is_active": False}, headers=mum)
    return {"mum": mum, "dad": dad, "mum_id": user_id(client, mum, "mum"), "dad_id": user_id(client, mum, "dad")}


def halves(parents, mum=50):
    return {parents["mum_id"]: mum, parents["dad_id"]: 100 - mum}


def test_create_and_list_splits(client, parents):
    created = create_split(client, parents["mum"], "Equal", halves(parents))
    assert created.status_code == 200
    assert created.json()["shares"] == halves(parents)
    listed = client.get(f"{BASE_URL}/splits", headers=parents["dad"]).json()
    assert [s["name"] for s in listed] == ["Equal"]


def test_split_validation(client, parents):
    mum = parents["mum"]
    assert create_split(client, mum, "Bad sum", halves(parents) | {parents["dad_id"]: 40}).status_code == 400
    assert create_split(client, mum, "Missing", {parents["mum_id"]: 100}).status_code == 400
    assert create_split(client, mum, "Negative", halves(parents, mum=110)).status_code == 422
    create_split(client, mum, "Equal", halves(parents))
    assert create_split(client, mum, "Equal", halves(parents)).status_code == 400
    for i, ratio in enumerate([60, 70, 80]):
        assert create_split(client, mum, f"S{i}", halves(parents, mum=ratio)).status_code == 200
    assert create_split(client, mum, "Fifth", halves(parents, mum=90)).status_code == 400


def test_children_cannot_use_splits(client, parents):
    teen = register(client, "teen", role="CHILD", by=parents["mum"])
    assert client.get(f"{BASE_URL}/splits", headers=teen).status_code == 403
    assert create_split(client, teen, "Equal", halves(parents)).status_code == 403


def test_edit_and_delete_split(client, parents):
    split = create_split(client, parents["mum"], "Equal", halves(parents)).json()
    edited = client.put(
        f"{BASE_URL}/splits/{split['id']}",
        json={"name": "By income", "shares": halves(parents, mum=70)},
        headers=parents["dad"],
    )
    assert edited.status_code == 200 and edited.json()["shares"][parents["mum_id"]] == 70
    assert client.delete(f"{BASE_URL}/splits/{split['id']}", headers=parents["dad"]).status_code == 200
    assert client.get(f"{BASE_URL}/splits", headers=parents["mum"]).json() == []


def test_new_parent_must_be_added_when_editing(client, parents):
    split = create_split(client, parents["mum"], "Equal", halves(parents)).json()
    client.post(f"{BASE_URL}/users", json={"username": "grandma", "pin": "1234", "role": "PARENT"}, headers=parents["mum"])
    # Listing still works with the new parent missing
    assert client.get(f"{BASE_URL}/splits", headers=parents["mum"]).status_code == 200
    # Saving requires a percent for every active parent
    again = client.put(f"{BASE_URL}/splits/{split['id']}", json={"name": "Equal", "shares": halves(parents)}, headers=parents["mum"])
    assert again.status_code == 400
```

- [ ] **Step 3: Run to verify failure**

Run: `$S/venv/bin/python -m pytest tests/test_common.py -q` — Expected: FAIL (404 on `/splits`).

- [ ] **Step 4: Model** — append to `models.py`:

```python
class Split(Base):
    """A preset ratio for dividing common costs between the parents, e.g. "By income" 70/30."""

    __tablename__ = "splits"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True)
    # {parent user id: whole percent}; sums to 100
    shares = Column(JSON, default={})
```

- [ ] **Step 5: Schemas** — append to `schemas.py`:

```python
# Split Schemas
Percent = Annotated[int, Field(ge=0, le=100)]


class SplitIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    shares: dict[str, Percent]


class Split(SplitIn):
    id: str

    class Config:
        from_attributes = True
```

- [ ] **Step 6: Router** — create `backend/app/common_api.py`:

```python
"""Common budget, splits, settlements, planned costs (yearly bills) and assets (investments). Parents only."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import auth, database, models, privacy, schemas

router = APIRouter()

MAX_SPLITS = 4


def require_parent(current_user: models.User = Depends(auth.get_current_user_from_token)) -> models.User:
    if current_user.role != models.UserRole.PARENT:
        raise HTTPException(status_code=403, detail="Only parents can use the common budget")
    return current_user


def get_split(db: Session, split_id: str) -> models.Split:
    split = db.query(models.Split).filter(models.Split.id == split_id).first()
    if not split:
        raise HTTPException(status_code=400, detail="Split not found")
    return split


def validate_split(db: Session, split: schemas.SplitIn, split_id: str | None = None) -> None:
    parent_ids = {p.id for p in privacy.active_parents(db)}
    if set(split.shares) != parent_ids:
        raise HTTPException(status_code=400, detail="Give every parent a percentage")
    if sum(split.shares.values()) != 100:
        raise HTTPException(status_code=400, detail="The percentages must add up to 100")
    same_name = db.query(models.Split).filter(models.Split.name == split.name, models.Split.id != split_id).first()
    if same_name:
        raise HTTPException(status_code=400, detail="A split with that name already exists")


@router.get("/splits", response_model=List[schemas.Split])
def list_splits(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    return db.query(models.Split).order_by(models.Split.name).all()


@router.post("/splits", response_model=schemas.Split)
def create_split(split: schemas.SplitIn, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    if db.query(models.Split).count() >= MAX_SPLITS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_SPLITS} splits")
    validate_split(db, split)
    db_split = models.Split(name=split.name, shares=split.shares)
    db.add(db_split)
    db.commit()
    db.refresh(db_split)
    return db_split


@router.put("/splits/{split_id}", response_model=schemas.Split)
def update_split(
    split_id: str, split: schemas.SplitIn, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    db_split = get_split(db, split_id)
    validate_split(db, split, split_id)
    db_split.name, db_split.shares = split.name, split.shares
    db.commit()
    db.refresh(db_split)
    return db_split


@router.delete("/splits/{split_id}", response_model=schemas.Split)
def delete_split(split_id: str, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    db_split = get_split(db, split_id)
    db.delete(db_split)
    db.commit()
    return db_split
```

(Task 6 and 7 add the "in use" check to `delete_split`.)

- [ ] **Step 7: Mount** — in `main.py`: `from . import models, database, api, common_api` and after the existing `include_router` add
`app.include_router(common_api.router, prefix="/api/v1")`.

- [ ] **Step 8: Run, lint, commit**

```bash
$S/venv/bin/python -m pytest tests -q
$S/venv/bin/black backend tests && $S/venv/bin/flake8 backend tests
git add backend tests
git commit -m "feat(common): preset splits between the parents"
```

---

### Task 4: Shared expenses and who owes whom

**Files:**
- Modify: `backend/app/models.py` (`Transaction.split_id`, `split_shares`, `asset_id`; `Asset`)
- Modify: `backend/app/migrate.py`
- Modify: `backend/app/schemas.py` (transaction fields; `Balance`, `SharedExpense`)
- Modify: `backend/app/crud.py` (`create_transaction`, `update_transaction`)
- Modify: `backend/app/api.py` (`check_shared`)
- Modify: `backend/app/common_api.py` (`/common/balance`, `/common/expenses`)
- Modify: `tests/test_common.py`, `tests/helpers.py`

**Interfaces:**
- Consumes: `finance.balances`, `finance.split_amount`, `common_api.get_split`.
- Produces: transaction JSON gains `split_id`, `split_shares`, `asset_id`;
  `GET /api/v1/common/balance -> [{"user_id": str, "amount": float}]` (positive = is owed);
  `GET /api/v1/common/expenses -> [{"transaction_id","date","description","amount","payer_id","split_name","shares": {uid: amount}}]` newest first;
  `common_api.shared_expense_rows(db) -> list[tuple[str, float, dict[str, int]]]` (input for `finance.balances`, used by Task 5).
- Test helper: `common_setup(client, parents) -> dict` with `mum_account`, `dad_account`, `groceries`, `equal`, `income70` (Task 5 reuses it).

- [ ] **Step 1: Helper** — append to `tests/helpers.py`:

```python
def balance_of(client, headers, uid):
    """What the parent is owed (positive) or owes (negative) in the common budget."""
    rows = client.get(f"{BASE_URL}/common/balance", headers=headers).json()
    return next((row["amount"] for row in rows if row["user_id"] == uid), 0.0)
```

- [ ] **Step 2: Failing tests** — append to `tests/test_common.py` (add `add_transaction, balance_of, category_id, create_account` to the helpers import):

```python
@pytest.fixture
def setup(client, parents):
    return {
        "mum_account": create_account(client, parents["mum"], "Mum bank"),
        "dad_account": create_account(client, parents["dad"], "Dad bank"),
        "groceries": category_id(client, "Groceries"),
        "equal": create_split(client, parents["mum"], "Equal", halves(parents)).json()["id"],
        "income70": create_split(client, parents["mum"], "By income", halves(parents, mum=70)).json()["id"],
    }


def test_shared_expense_balance(client, parents, setup):
    paid = add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 100, split_id=setup["equal"])
    assert paid.status_code == 200
    assert paid.json()["split_shares"] == halves(parents)
    # Mum's account drops by the full amount
    accounts = client.get(f"{BASE_URL}/accounts", headers=parents["mum"]).json()
    assert accounts[0]["balance"] == -100
    add_transaction(client, parents["dad"], setup["dad_account"], setup["groceries"], 40, split_id=setup["income70"])
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 22.0
    assert balance_of(client, parents["dad"], parents["dad_id"]) == -22.0


def test_editing_split_keeps_past_balances(client, parents, setup):
    add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 100, split_id=setup["equal"])
    client.put(
        f"{BASE_URL}/splits/{setup['equal']}", json={"name": "Equal", "shares": halves(parents, mum=90)}, headers=parents["mum"]
    )
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 50.0


def test_shared_expense_rules(client, parents, setup):
    salary = category_id(client, "Salary")
    assert (
        add_transaction(client, parents["mum"], setup["mum_account"], salary, 100, split_id=setup["equal"]).status_code
        == 400
    )
    assert add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 5, split_id="nope").status_code == 400
    teen = register(client, "teen", role="CHILD", by=parents["mum"])
    teen_account = create_account(client, teen, "Teen bank")
    assert add_transaction(client, teen, teen_account, setup["groceries"], 5, split_id=setup["equal"]).status_code == 400
    # Editing a shared expense into income is refused too
    shared = add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 10, split_id=setup["equal"])
    to_income = client.put(f"{BASE_URL}/transactions/{shared.json()['id']}", json={"category_id": salary}, headers=parents["mum"])
    assert to_income.status_code == 400


def test_unsharing_and_deleting_update_balance(client, parents, setup):
    shared = add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 100, split_id=setup["equal"]).json()
    client.put(f"{BASE_URL}/transactions/{shared['id']}", json={"split_id": setup["income70"]}, headers=parents["mum"])
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 30.0
    client.put(f"{BASE_URL}/transactions/{shared['id']}", json={"split_id": None}, headers=parents["mum"])
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 0.0
    client.put(f"{BASE_URL}/transactions/{shared['id']}", json={"split_id": setup["equal"]}, headers=parents["mum"])
    client.delete(f"{BASE_URL}/transactions/{shared['id']}", headers=parents["mum"])
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 0.0


def test_shared_expenses_visible_to_both_parents(client, parents, setup):
    add_transaction(
        client, parents["mum"], setup["mum_account"], setup["groceries"], 100, split_id=setup["equal"], description="Migros"
    )
    rows = client.get(f"{BASE_URL}/common/expenses", headers=parents["dad"]).json()
    assert len(rows) == 1
    assert rows[0]["description"] == "Migros" and rows[0]["payer_id"] == parents["mum_id"]
    assert rows[0]["amount"] == 100 and rows[0]["split_name"] == "Equal"
    assert rows[0]["shares"] == {parents["mum_id"]: 50.0, parents["dad_id"]: 50.0}
    # Dad still can't open Mum's account
    assert client.get(f"{BASE_URL}/accounts/{setup['mum_account']}/transactions", headers=parents["dad"]).status_code == 403


def test_three_parents(client, parents, setup):
    add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 90, split_id=setup["equal"])
    client.post(f"{BASE_URL}/users", json={"username": "grandma", "pin": "1234", "role": "PARENT"}, headers=parents["mum"])
    grandma_id = user_id(client, parents["mum"], "grandma")
    assert balance_of(client, parents["mum"], grandma_id) == 0.0
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 45.0
```

- [ ] **Step 3: Run to verify failure**

Run: `$S/venv/bin/python -m pytest tests/test_common.py -q` — Expected: new tests FAIL (`split_shares` missing / 404 on `/common/balance`).

- [ ] **Step 4: Model and migration** — in `models.Transaction` after `member_id`:

```python
    # Shared with the other parent(s): the split used, and its percents at booking time
    # (so editing the split later doesn't change past balances)
    split_id = Column(String, ForeignKey("splits.id"), nullable=True)
    split_shares = Column(JSON, nullable=True)
    # The investment this follow-up cost belongs to (repair, service, ...)
    asset_id = Column(String, ForeignKey("assets.id"), nullable=True)
```

In `migrate.NEW_COLUMNS["transactions"]` add:

```python
        "split_id": "VARCHAR REFERENCES splits(id)",
        "split_shares": "JSON",
        "asset_id": "VARCHAR REFERENCES assets(id)",
```

The `assets` table is defined now (filled with routes in Task 7) so the foreign key resolves and a database
created at this point already has all its columns. Append to `models.py` (add `Date`, `Integer` to the sqlalchemy import):

```python
class Asset(Base):
    """A long-lived purchase (TV, fridge, car, bike): planned for replacement, with its follow-up costs."""

    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    price = Column(Float)
    purchase_date = Column(Date)
    lifespan_years = Column(Integer)
    # Exactly one of: a parent (personal) or a split (common)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    split_id = Column(String, ForeignKey("splits.id"), nullable=True)
    notes = Column(String, nullable=True)
```

- [ ] **Step 5: Schemas** — in `TransactionBase` add `split_id: Optional[str] = None` and `asset_id: Optional[str] = None`;
in `TransactionUpdate` add the same two fields with the comment `# Send null to stop sharing / unlink`;
in `Transaction` add `split_shares: Optional[dict[str, int]] = None`. Append:

```python
class Balance(BaseModel):
    user_id: str
    # Positive: the other parents owe this parent; negative: this parent owes
    amount: float


class SharedExpense(BaseModel):
    transaction_id: str
    date: datetime
    description: Optional[str]
    amount: float
    payer_id: str
    split_name: Optional[str]
    shares: dict[str, float]
```

- [ ] **Step 6: Validation in `api.py`** — add below `check_member_tag`:

```python
def check_shared(db: Session, split_id: Optional[str], account_id: str, category) -> Optional[dict]:
    """A shared expense: an expense on a parent's account with an existing split. Returns the percents to keep."""
    if split_id is None:
        return None
    if category.type != models.CategoryType.EXPENSE:
        raise HTTPException(status_code=400, detail="Only expenses can be shared")
    owner = db.query(models.User).filter(models.User.id == crud.get_account(db, account_id).user_id).first()
    if not owner or owner.role != "PARENT":
        raise HTTPException(status_code=400, detail="Only a parent's expenses can be shared")
    split = db.query(models.Split).filter(models.Split.id == split_id).first()
    if not split:
        raise HTTPException(status_code=400, detail="Split not found")
    return dict(split.shares)
```

In `create_transaction`, after `check_member_tag(...)`:

```python
    split_shares = check_shared(db, transaction.split_id, transaction.account_id, category)
    return crud.create_transaction(db, transaction=transaction, category=category, split_shares=split_shares)
```

In `update_transaction`, replace the last two lines with the following. The percents are re-read only when
the split itself changes; otherwise the booked snapshot stays (also when that split was deleted since):

```python
    check_member_tag(db, transaction_update.member_id, db_transaction.account_id)
    fields = transaction_update.model_fields_set
    if "split_id" in fields and transaction_update.split_id != db_transaction.split_id:
        split_shares = check_shared(db, transaction_update.split_id, db_transaction.account_id, category)
    else:
        split_shares = db_transaction.split_shares
        if db_transaction.split_id and category.type != models.CategoryType.EXPENSE:
            raise HTTPException(status_code=400, detail="Only expenses can be shared")
    return crud.update_transaction(db, db_transaction, transaction_update, category, split_shares=split_shares)
```

- [ ] **Step 7: CRUD** — `create_transaction(db, transaction, category, split_shares=None)`: pass `split_id=transaction.split_id, split_shares=split_shares, asset_id=transaction.asset_id` to `models.Transaction(...)`.
`update_transaction(db, db_transaction, update, category, split_shares=None)`: after the `setattr` loop add `db_transaction.split_shares = split_shares`.

- [ ] **Step 8: Common routes** — append to `common_api.py` (add `from . import finance` to the imports):

```python
def shared_transactions(db: Session) -> list[tuple[models.Transaction, str]]:
    """Every shared expense with its payer's user id, newest first."""
    return (
        db.query(models.Transaction, models.Account.user_id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .filter(models.Transaction.split_id.isnot(None))
        .order_by(models.Transaction.date.desc())
        .all()
    )


def shared_expense_rows(db: Session) -> list[tuple[str, float, dict[str, int]]]:
    return [(payer, abs(t.amount), t.split_shares or {}) for t, payer in shared_transactions(db)]


def settlement_rows(db: Session) -> list[tuple[str, str, float]]:
    # Settlements are added in the next task; until then there are none
    return []


@router.get("/common/balance", response_model=List[schemas.Balance])
def common_balance(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    net = finance.balances(shared_expense_rows(db), settlement_rows(db))
    for parent in privacy.active_parents(db):
        net.setdefault(parent.id, 0.0)
    return [{"user_id": user_id, "amount": amount} for user_id, amount in net.items()]


@router.get("/common/expenses", response_model=List[schemas.SharedExpense])
def common_expenses(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    split_names = {s.id: s.name for s in db.query(models.Split)}
    return [
        {
            "transaction_id": t.id,
            "date": t.date,
            "description": t.description,
            "amount": abs(t.amount),
            "payer_id": payer,
            "split_name": split_names.get(t.split_id),
            "shares": finance.split_amount(abs(t.amount), t.split_shares or {}),
        }
        for t, payer in shared_transactions(db)
    ]
```

Deleting a split leaves `split_id` on old shared expenses (their snapshot keeps the percents, and
`common_expenses` shows `split_name` as `None`), so `delete_split` doesn't change here. Add a test for it to
`tests/test_common.py`:

```python
def test_deleted_split_keeps_balance(client, parents, setup):
    shared = add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 100, split_id=setup["equal"]).json()
    client.delete(f"{BASE_URL}/splits/{setup['equal']}", headers=parents["mum"])
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 50.0
    edited = client.put(f"{BASE_URL}/transactions/{shared['id']}", json={"description": "Coop"}, headers=parents["mum"])
    assert edited.status_code == 200
```

- [ ] **Step 9: Run, lint, commit**

```bash
$S/venv/bin/python -m pytest tests -q
$S/venv/bin/black backend tests && $S/venv/bin/flake8 backend tests
git add backend tests
git commit -m "feat(common): shared expenses with split snapshots and who-owes-whom balance"
```

---

### Task 5: Settling up

**Files:**
- Modify: `backend/app/models.py` (`Settlement`)
- Modify: `backend/app/schemas.py` (`SettlementCreate`, `Settlement`)
- Modify: `backend/app/common_api.py` (`settlement_rows`, routes)
- Modify: `tests/test_common.py`

**Interfaces:**
- Consumes: `seed.SETTLE_UP`, `crud.to_cents`, `crud.to_naive_utc`, `shared_expense_rows`.
- Produces: `POST /api/v1/settlements` body `{"from_user_id","to_user_id","amount","from_account_id","to_account_id","date"?}`; `GET /api/v1/settlements` (newest first); `DELETE /api/v1/settlements/{id}`.

- [ ] **Step 1: Failing tests** — append to `tests/test_common.py`:

```python
def settle(client, headers, parents, setup, amount):
    return client.post(
        f"{BASE_URL}/settlements",
        json={
            "from_user_id": parents["dad_id"],
            "to_user_id": parents["mum_id"],
            "amount": amount,
            "from_account_id": setup["dad_account"],
            "to_account_id": setup["mum_account"],
        },
        headers=headers,
    )


def test_settle_up(client, parents, setup):
    add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 100, split_id=setup["equal"])
    settled = settle(client, parents["dad"], parents, setup, 50)
    assert settled.status_code == 200
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 0.0
    balances = {a["name"]: a["balance"] for a in client.get(f"{BASE_URL}/accounts", headers=parents["mum"]).json()}
    assert balances == {"Mum bank": -50.0}
    dad_accounts = client.get(f"{BASE_URL}/accounts", headers=parents["dad"]).json()
    assert dad_accounts[0]["balance"] == -50.0
    assert [s["amount"] for s in client.get(f"{BASE_URL}/settlements", headers=parents["mum"]).json()] == [50.0]


def test_delete_settlement_undoes_it(client, parents, setup):
    add_transaction(client, parents["mum"], setup["mum_account"], setup["groceries"], 100, split_id=setup["equal"])
    settled = settle(client, parents["mum"], parents, setup, 50).json()
    assert client.delete(f"{BASE_URL}/settlements/{settled['id']}", headers=parents["mum"]).status_code == 200
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 50.0
    assert client.get(f"{BASE_URL}/accounts", headers=parents["dad"]).json()[0]["balance"] == 0.0


def test_settlement_rules(client, parents, setup):
    assert settle(client, parents["dad"], parents, setup, 0).status_code == 422
    wrong_account = settle(client, parents["dad"], parents, setup | {"dad_account": setup["mum_account"]}, 10)
    assert wrong_account.status_code == 400
    teen = register(client, "teen", role="CHILD", by=parents["mum"])
    assert settle(client, teen, parents, setup, 10).status_code == 403
    same = client.post(
        f"{BASE_URL}/settlements",
        json={
            "from_user_id": parents["mum_id"],
            "to_user_id": parents["mum_id"],
            "amount": 5,
            "from_account_id": setup["mum_account"],
            "to_account_id": setup["mum_account"],
        },
        headers=parents["mum"],
    )
    assert same.status_code == 400
```

- [ ] **Step 2: Run to verify failure** — `$S/venv/bin/python -m pytest tests/test_common.py -q`; Expected: settlement tests FAIL (404).

- [ ] **Step 3: Model** — append to `models.py`:

```python
class Settlement(Base):
    """One parent paid another to settle the common budget; booked as two transfer transactions."""

    __tablename__ = "settlements"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    from_user_id = Column(String, ForeignKey("users.id"))
    to_user_id = Column(String, ForeignKey("users.id"))
    amount = Column(Float)
    date = Column(DateTime, default=datetime.utcnow)
    from_transaction_id = Column(String, ForeignKey("transactions.id"))
    to_transaction_id = Column(String, ForeignKey("transactions.id"))
```

- [ ] **Step 4: Schemas** — append:

```python
class SettlementCreate(BaseModel):
    from_user_id: str
    to_user_id: str
    amount: float = Field(gt=0)
    from_account_id: str
    to_account_id: str
    date: Optional[datetime] = None


class Settlement(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    amount: float
    date: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 5: Routes** — in `common_api.py` add `from datetime import datetime`, `from . import crud`, `from .seed import SETTLE_UP`; replace `settlement_rows` with:

```python
def settlement_rows(db: Session) -> list[tuple[str, str, float]]:
    return [(s.from_user_id, s.to_user_id, s.amount) for s in db.query(models.Settlement)]
```

and append:

```python
def parent_account(db: Session, account_id: str, user_id: str) -> models.Account:
    account = crud.get_account(db, account_id)
    if not account or account.user_id != user_id:
        raise HTTPException(status_code=400, detail="Pick an account of each parent")
    return account


@router.get("/settlements", response_model=List[schemas.Settlement])
def list_settlements(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    return db.query(models.Settlement).order_by(models.Settlement.date.desc()).all()


@router.post("/settlements", response_model=schemas.Settlement)
def create_settlement(
    settlement: schemas.SettlementCreate,
    _: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    parent_ids = {p.id for p in privacy.active_parents(db)}
    if settlement.from_user_id == settlement.to_user_id or not {settlement.from_user_id, settlement.to_user_id} <= parent_ids:
        raise HTTPException(status_code=400, detail="Settling up is between two parents")
    from_account = parent_account(db, settlement.from_account_id, settlement.from_user_id)
    to_account = parent_account(db, settlement.to_account_id, settlement.to_user_id)
    category = db.query(models.Category).filter(models.Category.name == SETTLE_UP).one()
    amount = crud.to_cents(settlement.amount)
    when = crud.to_naive_utc(settlement.date) if settlement.date else datetime.utcnow()

    paid = models.Transaction(account_id=from_account.id, category_id=category.id, amount=-amount, date=when, description="Settle up")
    received = models.Transaction(account_id=to_account.id, category_id=category.id, amount=amount, date=when, description="Settle up")
    db.add_all([paid, received])
    from_account.balance = crud.to_cents(from_account.balance - amount)
    to_account.balance = crud.to_cents(to_account.balance + amount)
    db.flush()
    db_settlement = models.Settlement(
        from_user_id=settlement.from_user_id,
        to_user_id=settlement.to_user_id,
        amount=amount,
        date=when,
        from_transaction_id=paid.id,
        to_transaction_id=received.id,
    )
    db.add(db_settlement)
    db.commit()
    db.refresh(db_settlement)
    return db_settlement


@router.delete("/settlements/{settlement_id}", response_model=schemas.Settlement)
def delete_settlement(settlement_id: str, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    db_settlement = db.query(models.Settlement).filter(models.Settlement.id == settlement_id).first()
    if not db_settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    for transaction_id in (db_settlement.from_transaction_id, db_settlement.to_transaction_id):
        transaction = crud.get_transaction(db, transaction_id)
        if transaction:
            crud.delete_transaction(db, transaction)
    db.delete(db_settlement)
    db.commit()
    return db_settlement
```

Also: deleting one of the two transfer transactions directly would unbalance a settlement (editing is already
refused by Task 2's transfer check). In `api.delete_transaction`, after loading `db_transaction`, add:

```python
    if crud.get_category(db, db_transaction.category_id).type == models.CategoryType.TRANSFER:
        raise HTTPException(status_code=400, detail="Delete the settlement in the Common tab instead")
```

and a test line in `test_settle_up`:

```python
    transfer_id = client.get(f"{BASE_URL}/accounts/{setup['mum_account']}/transactions", headers=parents["mum"]).json()[0]["id"]
    assert client.delete(f"{BASE_URL}/transactions/{transfer_id}", headers=parents["mum"]).status_code == 400
```

- [ ] **Step 6: Run, lint, commit**

```bash
$S/venv/bin/python -m pytest tests -q
$S/venv/bin/black backend tests && $S/venv/bin/flake8 backend tests
git add backend tests
git commit -m "feat(common): settle up between parents"
```

---

### Task 6: Planned costs (yearly bills, common monthly costs) and the monthly overview

**Files:**
- Modify: `backend/app/models.py` (`Frequency`, `PlannedCost`)
- Modify: `backend/app/schemas.py` (`PlannedCostIn`, `PlannedCost`, `OverviewItem`, `Overview`)
- Modify: `backend/app/common_api.py`
- Create: `tests/test_planned_costs.py`

**Interfaces:**
- Consumes: `finance.monthly_equivalent`, `finance.next_due`, `finance.is_due_soon`, `finance.split_amount`, `get_split`, `require_parent`.
- Produces:
  - `GET /api/v1/planned-costs?frequency=YEARLY|MONTHLY` → list of PlannedCost with computed `monthly`, `next_due` (date or null), `due_soon`, `shares` ({uid: monthly amount} for common, {owner: monthly} for personal);
  - `POST /api/v1/planned-costs`, `PUT/DELETE /api/v1/planned-costs/{id}`;
  - `GET /api/v1/common/overview` → `{"items": [{"kind": "planned"|"asset", "id", "name", "monthly", "shares": {uid: amount}}], "totals": {uid: amount}}`;
  - `common_api.visible_owner(db, current_user, owner_id, split_id, write=False) -> bool`;
  - `common_api.today() -> date` (tests monkeypatch it).

- [ ] **Step 1: Failing tests** — create `tests/test_planned_costs.py`:

```python
"""Yearly bills and common monthly costs, with set-asides and each parent's monthly share."""

from datetime import date

import pytest

from app import common_api
from helpers import BASE_URL, category_id, create_split, register, user_id


@pytest.fixture
def parents(client, monkeypatch):
    monkeypatch.setattr(common_api, "today", lambda: date(2026, 11, 20))
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/users/{user_id(client, mum, 'Admin')}", json={"is_active": False}, headers=mum)
    mum_id, dad_id = user_id(client, mum, "mum"), user_id(client, mum, "dad")
    split = create_split(client, mum, "By income", {mum_id: 70, dad_id: 30}).json()["id"]
    return {"mum": mum, "dad": dad, "mum_id": mum_id, "dad_id": dad_id, "split": split}


def add_cost(client, headers, **fields):
    body = {"name": "Insurance", "category_id": category_id(client, "Healthcare"), "amount": 1200, "frequency": "YEARLY", "due_month": 1}
    return client.post(f"{BASE_URL}/planned-costs", json=body | fields, headers=headers)


def test_common_yearly_bill(client, parents):
    created = add_cost(client, parents["mum"], split_id=parents["split"])
    assert created.status_code == 200
    bill = client.get(f"{BASE_URL}/planned-costs", params={"frequency": "YEARLY"}, headers=parents["dad"]).json()[0]
    assert bill["monthly"] == 100
    assert bill["next_due"] == "2027-01-01" and bill["due_soon"] is True
    assert bill["shares"] == {parents["mum_id"]: 70.0, parents["dad_id"]: 30.0}


def test_personal_bill_private_unless_shared(client, parents):
    add_cost(client, parents["mum"], owner_id=parents["mum_id"], name="Phone", due_month=6)
    assert client.get(f"{BASE_URL}/planned-costs", headers=parents["dad"]).json() == []
    client.put(f"{BASE_URL}/shares/{parents['dad_id']}", json={"level": "VIEW"}, headers=parents["mum"])
    bills = client.get(f"{BASE_URL}/planned-costs", headers=parents["dad"]).json()
    assert [b["name"] for b in bills] == ["Phone"]
    assert bills[0]["due_soon"] is False
    assert client.delete(f"{BASE_URL}/planned-costs/{bills[0]['id']}", headers=parents["dad"]).status_code == 404


def test_planned_cost_validation(client, parents):
    mum = parents["mum"]
    assert add_cost(client, mum).status_code == 400  # neither owner nor split
    assert add_cost(client, mum, owner_id=parents["mum_id"], split_id=parents["split"]).status_code == 400
    assert add_cost(client, mum, owner_id=parents["mum_id"], due_month=None).status_code == 400
    assert add_cost(client, mum, owner_id=parents["mum_id"], frequency="MONTHLY", due_month=None).status_code == 400
    assert add_cost(client, mum, owner_id=parents["dad_id"]).status_code == 403
    assert add_cost(client, mum, owner_id=parents["mum_id"], due_month=13).status_code == 422
    assert add_cost(client, mum, owner_id=parents["mum_id"], amount=-5).status_code == 422
    teen = register(client, "teen", role="CHILD", by=parents["mum"])
    assert client.get(f"{BASE_URL}/planned-costs", headers=teen).status_code == 403


def test_monthly_overview(client, parents):
    add_cost(client, parents["mum"], split_id=parents["split"])  # 1200 a year -> 100 a month
    add_cost(client, parents["mum"], name="Rent", frequency="MONTHLY", due_month=None, amount=2000, split_id=parents["split"])
    add_cost(client, parents["mum"], name="Phone", owner_id=parents["mum_id"])  # personal: not in the common overview
    overview = client.get(f"{BASE_URL}/common/overview", headers=parents["dad"]).json()
    assert sorted(item["name"] for item in overview["items"]) == ["Insurance", "Rent"]
    assert overview["totals"] == {parents["mum_id"]: 1470.0, parents["dad_id"]: 630.0}


def test_edit_and_split_in_use(client, parents):
    bill = add_cost(client, parents["mum"], split_id=parents["split"]).json()
    edited = client.put(f"{BASE_URL}/planned-costs/{bill['id']}", json={**bill, "amount": 600}, headers=parents["dad"])
    assert edited.status_code == 200 and edited.json()["monthly"] == 50
    assert client.delete(f"{BASE_URL}/splits/{parents['split']}", headers=parents["mum"]).status_code == 409
    assert client.delete(f"{BASE_URL}/planned-costs/{bill['id']}", headers=parents["dad"]).status_code == 200
    assert client.delete(f"{BASE_URL}/splits/{parents['split']}", headers=parents["mum"]).status_code == 200
```

- [ ] **Step 2: Run to verify failure** — `$S/venv/bin/python -m pytest tests/test_planned_costs.py -q`; Expected: FAIL (404).

- [ ] **Step 3: Model** — in `models.py` add (and `Integer` to the sqlalchemy import):

```python
class Frequency(str, enum.Enum):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class PlannedCost(Base):
    """A recurring cost planned ahead: a yearly bill (personal or common) or a common monthly cost."""

    __tablename__ = "planned_costs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    category_id = Column(String, ForeignKey("categories.id"))
    amount = Column(Float)
    frequency = Column(Enum(Frequency))
    due_month = Column(Integer, nullable=True)
    # Exactly one of: a parent (personal) or a split (common)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    split_id = Column(String, ForeignKey("splits.id"), nullable=True)
    notes = Column(String, nullable=True)
```

- [ ] **Step 4: Schemas** — append (add `date` to the `datetime` import):

```python
class PlannedCostIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    category_id: str
    amount: float = Field(gt=0)
    frequency: Literal["MONTHLY", "YEARLY"]
    due_month: Optional[int] = Field(default=None, ge=1, le=12)
    owner_id: Optional[str] = None
    split_id: Optional[str] = None
    notes: Optional[str] = None


class PlannedCost(PlannedCostIn):
    id: str
    monthly: float
    next_due: Optional[date]
    due_soon: bool
    # Monthly amount per parent
    shares: dict[str, float]


class OverviewItem(BaseModel):
    kind: Literal["planned", "asset"]
    id: str
    name: str
    monthly: float
    shares: dict[str, float]


class Overview(BaseModel):
    items: list[OverviewItem]
    totals: dict[str, float]
```

- [ ] **Step 5: Routes** — append to `common_api.py` (add `from datetime import date, datetime` and `from typing import List, Optional`):

```python
def today() -> date:
    return date.today()


def visible_owner(db: Session, current_user: models.User, owner_id: Optional[str], split_id: Optional[str], write: bool = False) -> bool:
    """Common items belong to all parents; a personal item follows its owner's share."""
    if split_id:
        return True
    owner = db.query(models.User).filter(models.User.id == owner_id).first()
    level = privacy.access_level(db, current_user, owner) if owner else None
    return privacy.can_write(level) if write else level is not None


def check_owner(db: Session, current_user: models.User, owner_id: Optional[str], split_id: Optional[str]) -> None:
    if bool(owner_id) == bool(split_id):
        raise HTTPException(status_code=400, detail="Choose either an owner or a split")
    if split_id:
        get_split(db, split_id)
    elif not visible_owner(db, current_user, owner_id, None, write=True):
        raise HTTPException(status_code=403, detail="You can't manage that parent's items")


def monthly_shares(db: Session, monthly: float, owner_id: Optional[str], split_id: Optional[str]) -> dict[str, float]:
    if split_id:
        split = db.query(models.Split).filter(models.Split.id == split_id).first()
        return finance.split_amount(monthly, split.shares if split else {})
    return {owner_id: monthly} if owner_id else {}


def planned_cost_out(db: Session, cost: models.PlannedCost) -> dict:
    monthly = finance.monthly_equivalent(cost.amount, cost.frequency.value)
    due = finance.next_due(cost.due_month, today()) if cost.due_month else None
    return {
        **{c: getattr(cost, c) for c in ("id", "name", "category_id", "amount", "due_month", "owner_id", "split_id", "notes")},
        "frequency": cost.frequency.value,
        "monthly": monthly,
        "next_due": due,
        "due_soon": bool(due and finance.is_due_soon(due, today())),
        "shares": monthly_shares(db, monthly, cost.owner_id, cost.split_id),
    }


def validate_planned_cost(db: Session, current_user: models.User, cost: schemas.PlannedCostIn) -> None:
    check_owner(db, current_user, cost.owner_id, cost.split_id)
    if cost.frequency == "YEARLY" and not cost.due_month:
        raise HTTPException(status_code=400, detail="Choose the month the bill is due")
    if cost.frequency == "MONTHLY" and not cost.split_id:
        raise HTTPException(status_code=400, detail="Monthly planned costs are common costs; choose a split")
    if not db.query(models.Category).filter(models.Category.id == cost.category_id).first():
        raise HTTPException(status_code=400, detail="Category not found")


def get_planned_cost(db: Session, current_user: models.User, cost_id: str, write: bool = False) -> models.PlannedCost:
    cost = db.query(models.PlannedCost).filter(models.PlannedCost.id == cost_id).first()
    if not cost or not visible_owner(db, current_user, cost.owner_id, cost.split_id, write):
        raise HTTPException(status_code=404, detail="Planned cost not found")
    return cost


@router.get("/planned-costs", response_model=List[schemas.PlannedCost])
def list_planned_costs(
    frequency: Optional[str] = None,
    current_user: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.PlannedCost)
    if frequency:
        query = query.filter(models.PlannedCost.frequency == frequency)
    costs = [c for c in query if visible_owner(db, current_user, c.owner_id, c.split_id)]
    rows = [planned_cost_out(db, c) for c in costs]
    return sorted(rows, key=lambda r: (r["next_due"] or date.max, r["name"]))


@router.post("/planned-costs", response_model=schemas.PlannedCost)
def create_planned_cost(
    cost: schemas.PlannedCostIn, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    validate_planned_cost(db, current_user, cost)
    data = cost.model_dump()
    data["amount"] = finance.cents(data["amount"])
    db_cost = models.PlannedCost(**data)
    db.add(db_cost)
    db.commit()
    db.refresh(db_cost)
    return planned_cost_out(db, db_cost)


@router.put("/planned-costs/{cost_id}", response_model=schemas.PlannedCost)
def update_planned_cost(
    cost_id: str,
    cost: schemas.PlannedCostIn,
    current_user: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    db_cost = get_planned_cost(db, current_user, cost_id, write=True)
    validate_planned_cost(db, current_user, cost)
    for key, value in cost.model_dump().items():
        setattr(db_cost, key, finance.cents(value) if key == "amount" else value)
    db.commit()
    db.refresh(db_cost)
    return planned_cost_out(db, db_cost)


@router.delete("/planned-costs/{cost_id}")
def delete_planned_cost(cost_id: str, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    db.delete(get_planned_cost(db, current_user, cost_id, write=True))
    db.commit()
    return {"deleted": cost_id}


@router.get("/common/overview", response_model=schemas.Overview)
def common_overview(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    items = []
    for cost in db.query(models.PlannedCost).filter(models.PlannedCost.split_id.isnot(None)):
        monthly = finance.monthly_equivalent(cost.amount, cost.frequency.value)
        items.append({"kind": "planned", "id": cost.id, "name": cost.name, "monthly": monthly,
                      "shares": monthly_shares(db, monthly, None, cost.split_id)})
    items += common_asset_items(db)
    totals: dict[str, float] = {}
    for item in items:
        for user_id, amount in item["shares"].items():
            totals[user_id] = finance.cents(totals.get(user_id, 0.0) + amount)
    return {"items": items, "totals": totals}


def common_asset_items(db: Session) -> list[dict]:
    # Common investments are added in the next task
    return []
```

In `delete_split`, before `db.delete(db_split)`, add:

```python
    if db.query(models.PlannedCost).filter(models.PlannedCost.split_id == split_id).first():
        raise HTTPException(status_code=409, detail="In use by a planned cost; change or delete it first")
```

- [ ] **Step 6: Run, lint, commit**

```bash
$S/venv/bin/python -m pytest tests -q
$S/venv/bin/black backend tests && $S/venv/bin/flake8 backend tests
git add backend tests
git commit -m "feat(planning): yearly bills and common monthly costs with each parent's share"
```

---

### Task 7: Investments (assets) and cleanup when a parent is deleted

**Files:**
- Modify: `backend/app/schemas.py` (`AssetIn`, `Asset`, `AssetDetail`)
- Modify: `backend/app/common_api.py` (asset routes, `common_asset_items`, split in-use check)
- Modify: `backend/app/api.py` (`check_asset` on transactions)
- Modify: `backend/app/crud.py` (`delete_user` cleanup)
- Create: `tests/test_assets.py`

**Interfaces:**
- Consumes: `finance.asset_stats`, `visible_owner`, `check_owner`, `monthly_shares`, `today`.
- Produces: `GET /api/v1/assets` (each with stats); `GET /api/v1/assets/{id}` (adds `expenses: [Transaction]`); `POST`, `PUT/DELETE /api/v1/assets/{id}`; transactions accept `asset_id`.

- [ ] **Step 1: Failing tests** — create `tests/test_assets.py`:

```python
"""Investments: replacement planning, inventory notes and total cost of ownership."""

from datetime import date

import pytest

from app import common_api
from helpers import BASE_URL, add_transaction, category_id, create_account, create_split, register, user_id


@pytest.fixture
def parents(client, monkeypatch):
    monkeypatch.setattr(common_api, "today", lambda: date(2026, 10, 14))
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/users/{user_id(client, mum, 'Admin')}", json={"is_active": False}, headers=mum)
    mum_id, dad_id = user_id(client, mum, "mum"), user_id(client, mum, "dad")
    return {
        "mum": mum,
        "dad": dad,
        "mum_id": mum_id,
        "dad_id": dad_id,
        "split": create_split(client, mum, "Equal", {mum_id: 50, dad_id: 50}).json()["id"],
        "mum_account": create_account(client, mum, "Mum bank"),
    }


def add_asset(client, headers, **fields):
    body = {"name": "Car", "price": 24000, "purchase_date": "2022-10-14", "lifespan_years": 8}
    return client.post(f"{BASE_URL}/assets", json=body | fields, headers=headers)


def test_common_asset_with_follow_up_costs(client, parents):
    car = add_asset(client, parents["mum"], split_id=parents["split"], notes="Warranty until 2027").json()
    assert car["monthly_set_aside"] == 250 and car["age_years"] == 4.0
    assert car["replacement_due"] == "2030-10-14" and car["is_due"] is False
    transport = category_id(client, "Transportation")
    service = add_transaction(client, parents["mum"], parents["mum_account"], transport, 600, asset_id=car["id"])
    assert service.status_code == 200
    detail = client.get(f"{BASE_URL}/assets/{car['id']}", headers=parents["dad"]).json()
    assert detail["total_cost"] == 24600 and detail["cost_per_year"] == 6150
    assert [e["amount"] for e in detail["expenses"]] == [-600]
    # Dad sees the linked expense on the asset, not Mum's account
    assert client.get(f"{BASE_URL}/accounts/{parents['mum_account']}/transactions", headers=parents["dad"]).status_code == 403


def test_asset_in_monthly_overview(client, parents):
    add_asset(client, parents["mum"], split_id=parents["split"])
    add_asset(client, parents["mum"], name="Bike", price=3000, lifespan_years=5, owner_id=parents["mum_id"])
    overview = client.get(f"{BASE_URL}/common/overview", headers=parents["dad"]).json()
    assert [item["name"] for item in overview["items"]] == ["Car"]
    assert overview["totals"] == {parents["mum_id"]: 125.0, parents["dad_id"]: 125.0}


def test_personal_asset_visibility_and_validation(client, parents):
    bike = add_asset(client, parents["mum"], name="Bike", owner_id=parents["mum_id"]).json()
    assert client.get(f"{BASE_URL}/assets", headers=parents["dad"]).json() == []
    assert client.get(f"{BASE_URL}/assets/{bike['id']}", headers=parents["dad"]).status_code == 404
    assert add_asset(client, parents["mum"], lifespan_years=0, owner_id=parents["mum_id"]).status_code == 422
    assert add_asset(client, parents["mum"]).status_code == 400
    # Linking to an asset you can't see is refused
    transport = category_id(client, "Transportation")
    dad_account = create_account(client, parents["dad"], "Dad bank")
    assert add_transaction(client, parents["dad"], dad_account, transport, 10, asset_id=bike["id"]).status_code == 400


def test_deleting_asset_keeps_expenses(client, parents):
    car = add_asset(client, parents["mum"], split_id=parents["split"]).json()
    transport = category_id(client, "Transportation")
    expense = add_transaction(client, parents["mum"], parents["mum_account"], transport, 80, asset_id=car["id"]).json()
    assert client.delete(f"{BASE_URL}/splits/{parents['split']}", headers=parents["mum"]).status_code == 409
    assert client.delete(f"{BASE_URL}/assets/{car['id']}", headers=parents["dad"]).status_code == 200
    kept = client.get(f"{BASE_URL}/accounts/{parents['mum_account']}/transactions", headers=parents["mum"]).json()
    assert [t["id"] for t in kept] == [expense["id"]] and kept[0]["asset_id"] is None


def test_deleting_parent_cleans_up(client, parents):
    add_asset(client, parents["dad"], name="Bike", owner_id=parents["dad_id"])
    client.post(
        f"{BASE_URL}/planned-costs",
        json={"name": "Phone", "category_id": category_id(client, "Utilities"), "amount": 300,
              "frequency": "YEARLY", "due_month": 3, "owner_id": parents["dad_id"]},
        headers=parents["dad"],
    )
    dad_account = create_account(client, parents["dad"], "Dad bank")
    groceries = category_id(client, "Groceries")
    add_transaction(client, parents["dad"], dad_account, groceries, 40, split_id=parents["split"])
    client.post(
        f"{BASE_URL}/settlements",
        json={"from_user_id": parents["mum_id"], "to_user_id": parents["dad_id"], "amount": 20,
              "from_account_id": parents["mum_account"], "to_account_id": dad_account},
        headers=parents["mum"],
    )
    client.put(f"{BASE_URL}/shares/{parents['mum_id']}", json={"level": "EDIT"}, headers=parents["dad"])

    assert client.delete(f"{BASE_URL}/users/{parents['dad_id']}", headers=parents["mum"]).status_code == 200
    for path in ("/common/balance", "/common/expenses", "/common/overview", "/settlements", "/assets", "/planned-costs", "/splits"):
        assert client.get(f"{BASE_URL}{path}", headers=parents["mum"]).status_code == 200, path
    assert client.get(f"{BASE_URL}/settlements", headers=parents["mum"]).json() == []
    assert client.get(f"{BASE_URL}/assets", headers=parents["mum"]).json() == []
    # The split no longer names the deleted parent
    assert list(client.get(f"{BASE_URL}/splits", headers=parents["mum"]).json()[0]["shares"]) == [parents["mum_id"]]
```

- [ ] **Step 2: Run to verify failure** — `$S/venv/bin/python -m pytest tests/test_assets.py -q`; Expected: FAIL.

- [ ] **Step 3: Model** — `models.Asset` already exists (Task 4). Nothing to add.

- [ ] **Step 4: Schemas** — append:

```python
class AssetIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    price: float = Field(gt=0)
    purchase_date: date
    lifespan_years: int = Field(ge=1, le=100)
    owner_id: Optional[str] = None
    split_id: Optional[str] = None
    notes: Optional[str] = None


class Asset(AssetIn):
    id: str
    age_years: float
    replacement_due: date
    is_due: bool
    monthly_set_aside: float
    total_cost: float
    cost_per_year: float
    # Monthly set-aside per parent
    shares: dict[str, float]


class AssetDetail(Asset):
    expenses: list[Transaction]
```

- [ ] **Step 5: Routes** — append to `common_api.py`:

```python
def asset_out(db: Session, asset: models.Asset) -> dict:
    follow_ups = db.query(models.Transaction).filter(models.Transaction.asset_id == asset.id).all()
    stats = finance.asset_stats(
        asset.price, asset.purchase_date, asset.lifespan_years, sum(abs(t.amount) for t in follow_ups), today()
    )
    fields = ("id", "name", "price", "purchase_date", "lifespan_years", "owner_id", "split_id", "notes")
    return {
        **{f: getattr(asset, f) for f in fields},
        **stats,
        "shares": monthly_shares(db, stats["monthly_set_aside"], asset.owner_id, asset.split_id),
    }


def get_asset(db: Session, current_user: models.User, asset_id: str, write: bool = False) -> models.Asset:
    asset = db.query(models.Asset).filter(models.Asset.id == asset_id).first()
    if not asset or not visible_owner(db, current_user, asset.owner_id, asset.split_id, write):
        raise HTTPException(status_code=404, detail="Investment not found")
    return asset


def common_asset_items(db: Session) -> list[dict]:
    items = []
    for asset in db.query(models.Asset).filter(models.Asset.split_id.isnot(None)):
        monthly = finance.cents(asset.price / (asset.lifespan_years * 12))
        items.append({"kind": "asset", "id": asset.id, "name": asset.name, "monthly": monthly,
                      "shares": monthly_shares(db, monthly, None, asset.split_id)})
    return items


@router.get("/assets", response_model=List[schemas.Asset])
def list_assets(current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    assets = [a for a in db.query(models.Asset) if visible_owner(db, current_user, a.owner_id, a.split_id)]
    return sorted((asset_out(db, a) for a in assets), key=lambda a: a["replacement_due"])


@router.get("/assets/{asset_id}", response_model=schemas.AssetDetail)
def read_asset(asset_id: str, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    asset = get_asset(db, current_user, asset_id)
    expenses = (
        db.query(models.Transaction)
        .filter(models.Transaction.asset_id == asset.id)
        .order_by(models.Transaction.date.desc())
        .all()
    )
    return {**asset_out(db, asset), "expenses": expenses}


@router.post("/assets", response_model=schemas.Asset)
def create_asset(asset: schemas.AssetIn, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    check_owner(db, current_user, asset.owner_id, asset.split_id)
    data = asset.model_dump()
    data["price"] = finance.cents(data["price"])
    db_asset = models.Asset(**data)
    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)
    return asset_out(db, db_asset)


@router.put("/assets/{asset_id}", response_model=schemas.Asset)
def update_asset(
    asset_id: str, asset: schemas.AssetIn, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    db_asset = get_asset(db, current_user, asset_id, write=True)
    check_owner(db, current_user, asset.owner_id, asset.split_id)
    for key, value in asset.model_dump().items():
        setattr(db_asset, key, finance.cents(value) if key == "price" else value)
    db.commit()
    db.refresh(db_asset)
    return asset_out(db, db_asset)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    asset = get_asset(db, current_user, asset_id, write=True)
    # The follow-up expenses stay as normal expenses
    db.query(models.Transaction).filter(models.Transaction.asset_id == asset.id).update(
        {models.Transaction.asset_id: None}, synchronize_session=False
    )
    db.delete(asset)
    db.commit()
    return {"deleted": asset_id}
```

Delete the old `common_asset_items` stub from Task 6. In `delete_split`, extend the in-use check:

```python
    in_use = db.query(models.PlannedCost).filter(models.PlannedCost.split_id == split_id).first() or (
        db.query(models.Asset).filter(models.Asset.split_id == split_id).first()
    )
    if in_use:
        raise HTTPException(status_code=409, detail="In use by a planned cost or investment; change or delete it first")
```

(The planned-costs test expects 409 too; the message changes, the status doesn't.)

- [ ] **Step 6: Link check in `api.py`** — add:

```python
def check_asset(db: Session, current_user, asset_id: Optional[str]) -> None:
    """An expense can belong to an investment the current user can see."""
    if asset_id is None:
        return
    from .common_api import visible_owner

    asset = db.query(models.Asset).filter(models.Asset.id == asset_id).first()
    if not asset or not visible_owner(db, current_user, asset.owner_id, asset.split_id):
        raise HTTPException(status_code=400, detail="Investment not found")
```

Call `check_asset(db, current_user, transaction.asset_id)` in `create_transaction`, and in `update_transaction` when `"asset_id" in transaction_update.model_fields_set`: `check_asset(db, current_user, transaction_update.asset_id)`.
(The local import avoids a circular import, since `common_api` doesn't import `api`; if flake8/mypy prefer, move `visible_owner` into `privacy.py` instead and import it from both.)

- [ ] **Step 7: Cleanup in `crud.delete_user`** — before `db.delete(db_user)` add:

```python
    db.query(models.Settlement).filter(
        (models.Settlement.from_user_id == user_id) | (models.Settlement.to_user_id == user_id)
    ).delete(synchronize_session=False)
    for model in (models.PlannedCost, models.Asset):
        for item in db.query(model).filter(model.owner_id == user_id):
            if model is models.Asset:
                db.query(models.Transaction).filter(models.Transaction.asset_id == item.id).update(
                    {models.Transaction.asset_id: None}, synchronize_session=False
                )
            db.delete(item)
    # Splits stop naming the deleted parent; parents edit them to add up to 100 again
    for split in db.query(models.Split):
        if user_id in (split.shares or {}):
            split.shares = {k: v for k, v in split.shares.items() if k != user_id}
```

Note the settlement transactions on the remaining parent's account stay (their balance effect is real money that moved); only the settlement record goes. The deleted parent's own transactions (incl. shared expenses) are already removed with their accounts, so their balance disappears.

- [ ] **Step 8: Run, lint, commit**

```bash
$S/venv/bin/python -m pytest tests -q
$S/venv/bin/black backend tests && $S/venv/bin/flake8 backend tests
git add backend tests
git commit -m "feat(investments): assets with replacement planning and cost of ownership"
```

---

### Task 8: Frontend — private scopes, sharing setting, transfers out of analytics

**Files:**
- Modify: `frontend/src/family.ts`
- Modify: `frontend/src/useFamily.ts`
- Modify: `frontend/src/components/BudgetManager.tsx`
- Modify: `frontend/src/components/Analytics.tsx`
- Create: `frontend/src/components/ShareSettings.tsx`
- Modify: `frontend/src/pages/dashboard/Dashboard.tsx` (overview totals, edit permissions, settings)
- Modify: `frontend/src/components/DataManager.tsx:360` (privacy rules text)

**Interfaces:**
- Consumes: `GET /shares`, `PUT /shares/{grantee_id}`, `POST /accounts` and `/budgets` with `user_id`.
- Produces (`family.ts`):
  ```ts
  export type Access = 'OWN' | 'EDIT' | 'VIEW';
  export interface ShareInfo { owner_id: string; grantee_id: string; level: 'VIEW' | 'EDIT' }
  export interface Scope { key: string; label: string; userIds: string[]; budgetOwnerId?: string; access: Access }
  export function buildScopes(me: FamilyUser, users: FamilyUser[], shares: ShareInfo[]): Scope[]
  export function accessTo(me: FamilyUser, ownerId: string, users: FamilyUser[], shares: ShareInfo[]): Access | null
  ```
  `useFamily()` returns `{ users, scopes, shares, reload }`.

- [ ] **Step 1: `family.ts`** — replace the header comment, `Scope`, `HOUSEHOLD_SCOPE` and `buildScopes` with:

```ts
// Family model: each parent's money is private unless they share it with the other parent
// (view or edit). Costs the parents share go through the common budget. A child either has an
// own allowance (Jugendlohn: own accounts and budgets) or is a dependent whose costs are tagged.

export type Access = 'OWN' | 'EDIT' | 'VIEW';

export interface ShareInfo {
    owner_id: string;
    grantee_id: string;
    level: 'VIEW' | 'EDIT';
}

// A set of accounts and budgets viewed together in Budgets and Analytics
export interface Scope {
    key: string;
    label: string;
    // Owners of the accounts that count in this scope
    userIds: string[];
    // Set when looking at someone else's budgets
    budgetOwnerId?: string;
    access: Access;
}

// What the current user may do with the money of the account owner
export function accessTo(me: FamilyUser, ownerId: string, users: FamilyUser[], shares: ShareInfo[]): Access | null {
    if (ownerId === me.id) return 'OWN';
    if (me.role !== 'PARENT') return null;
    const owner = users.find(u => u.id === ownerId);
    if (!owner) return null;
    if (owner.role === 'PARENT') {
        return shares.find(s => s.owner_id === ownerId && s.grantee_id === me.id)?.level ?? null;
    }
    return owner.privacy_enabled ? null : 'VIEW';
}

export function buildScopes(me: FamilyUser, users: FamilyUser[], shares: ShareInfo[]): Scope[] {
    if (me.role !== 'PARENT') {
        return [{ key: me.id, label: 'My Money', userIds: [me.id], access: 'OWN' }];
    }

    const sharedParents = users.filter(u => u.role === 'PARENT' && u.id !== me.id && accessTo(me, u.id, users, shares));
    const allowanceChildren = users.filter(u => u.role === 'CHILD' && u.has_allowance);
    return [
        { key: me.id, label: 'My finances', userIds: [me.id], access: 'OWN' },
        ...sharedParents.map(parent => ({
            key: parent.id,
            label: `${parent.username}'s finances`,
            userIds: [parent.id],
            budgetOwnerId: parent.id,
            access: accessTo(me, parent.id, users, shares)!
        })),
        ...allowanceChildren.map(child => ({
            key: child.id,
            label: `${child.username} (own allowance)`,
            userIds: [child.id],
            budgetOwnerId: child.id,
            access: 'VIEW' as const
        }))
    ];
}
```

Keep `FamilyUser` and `dependents` unchanged; update the `dependents` comment to "costs can be tagged with them".

- [ ] **Step 2: `useFamily.ts`** — load shares too:

```ts
import { useCallback, useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './AuthContext';
import { buildScopes, type FamilyUser, type ShareInfo } from './family';

// Family members visible to the current user, what was shared, and the scopes they can switch between
export function useFamily() {
    const { user } = useAuth();
    const [users, setUsers] = useState<FamilyUser[]>([]);
    const [shares, setShares] = useState<ShareInfo[]>([]);
    // Bumped to load the family again after a change
    const [version, setVersion] = useState(0);

    useEffect(() => {
        api.get('/api/v1/users')
            .then(response => setUsers(response.data))
            .catch(error => console.error('Failed to load family members', error));
        api.get('/api/v1/shares')
            .then(response => setShares(response.data))
            .catch(error => console.error('Failed to load shares', error));
    }, [version]);

    const reload = useCallback(() => setVersion(v => v + 1), []);

    // Memoized so components can depend on the scopes in effects without reloading every render
    const scopes = useMemo(
        () => (user && users.length > 0 ? buildScopes(user, users, shares) : []),
        [user, users, shares]
    );
    return { users, scopes, shares, reload };
}
```

- [ ] **Step 3: `BudgetManager.tsx`**
  - import: `import type { Scope } from '../family';` (drop `HOUSEHOLD_SCOPE`); drop the unused `useAuth` import and `user` if nothing else uses them.
  - `useState(HOUSEHOLD_SCOPE)` → `useState('')` (falls back to the first scope: "My finances").
  - `canManage`: `const canManage = !!activeScope && activeScope.access !== 'VIEW';` with comment `// Own budgets, or a parent who shared with edit access; everything else is read only`.
  - `handleAddBudget` body: add `user_id: activeScope?.budgetOwnerId` to the POST payload.
  - In `loadBudgetsWithSpending`, change the comment to `// Only the scope's accounts count`.
  - The read-only note: replace its text with `Viewing {activeScope.label} (read only).`

- [ ] **Step 4: `Analytics.tsx`**
  - import `dependents` only from `../family`; `useState(HOUSEHOLD_SCOPE)` → `useState('')`.
  - After `setCategories(categoriesRes.data)`, keep transfers out of every chart and total:

```ts
                const transferIds = new Set(
                    (categoriesRes.data as Category[]).filter(c => c.type === 'TRANSFER').map(c => c.id)
                );
                // Settling up between parents moves money but is neither income nor spending
                setTransactions(scopeTransactions.filter(t => !transferIds.has(t.category_id)));
```

  (replacing `setTransactions(scopeTransactions);`).
  - Child costs condition: replace `activeScope?.key === HOUSEHOLD_SCOPE` with
    `users.find(u => u.id === activeScope?.userIds[0])?.role === 'PARENT'`; change the card subtitle to
    `Expenses tagged with a child. They're included in the totals above.`

- [ ] **Step 5: `ShareSettings.tsx`**

```tsx
import { useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';

type Level = 'NONE' | 'VIEW' | 'EDIT';

const LEVELS: Record<Level, string> = {
    NONE: "Don't share",
    VIEW: 'Can view',
    EDIT: 'Can view and manage'
};

// A parent decides whether the other parent may see (or manage) their accounts, transactions and budgets
export default function ShareSettings() {
    const { user } = useAuth();
    const { users, shares, reload } = useFamily();
    const [error, setError] = useState('');
    const otherParents = users.filter(u => u.role === 'PARENT' && u.id !== user?.id && u.is_active !== false);

    const levelFor = (granteeId: string): Level =>
        shares.find(s => s.owner_id === user?.id && s.grantee_id === granteeId)?.level ?? 'NONE';

    const setLevel = async (granteeId: string, level: Level) => {
        try {
            await api.put(`/api/v1/shares/${granteeId}`, { level });
            setError('');
            reload();
        } catch (err) {
            setError(errorMessage(err, 'Failed to save sharing'));
        }
    };

    if (otherParents.length === 0) return null;

    return (
        <div className="glass-card p-6">
            <h2 className="text-2xl font-bold mb-2">Sharing</h2>
            <p className="text-slate-400 mb-4 text-sm">
                Your accounts, transactions and budgets are private. Costs you share go through the Common tab,
                which both parents always see.
            </p>
            {error && <p className="mb-3 text-red-300">{error}</p>}
            <div className="space-y-3">
                {otherParents.map(parent => (
                    <label key={parent.id} className="flex flex-wrap items-center justify-between gap-3 p-4 bg-slate-800/30 rounded-lg">
                        <span>Share my finances with <strong>{parent.username}</strong></span>
                        <select
                            value={levelFor(parent.id)}
                            onChange={(e) => setLevel(parent.id, e.target.value as Level)}
                            className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                        >
                            {(Object.keys(LEVELS) as Level[]).map(level => (
                                <option key={level} value={level}>{LEVELS[level]}</option>
                            ))}
                        </select>
                    </label>
                ))}
            </div>
        </div>
    );
}
```

Add `is_active?: boolean;` to `FamilyUser` in `family.ts` (the API already returns it).

- [ ] **Step 6: `Dashboard.tsx` overview**
  - `const { users, shares } = useFamily();` and import `accessTo` from `../../family`.
  - Replace `isHouseholdAccount`, `balanceAccounts`, `totalBalance` with:

```ts
    const ownerOf = (account: Account) => users.find(u => u.id === account.user_id);
    const isParentAccount = (account: Account) => ownerOf(account)?.role === 'PARENT';
    const canEdit = (account: Account) => {
        const access = user ? accessTo(user, account.user_id, users, shares) : null;
        return access === 'OWN' || access === 'EDIT';
    };
    // Your own money; accounts others shared with you are listed but not added up
    const totalBalance = accounts.filter(a => a.user_id === user?.id).reduce((sum, acc) => sum + acc.balance, 0);
```

  - `canTagChild`: use `isParentAccount(selectedAccountObj)`.
  - Summary card title: `'My Balance'` for everyone.
  - Account card: show the Edit/Delete buttons when `canEdit(account)` (was `account.user_id === user?.id`); the owner line stays.
  - Transactions: hide "+ Add Transaction" and the ✎/✕ buttons unless `selectedAccountObj && canEdit(selectedAccountObj)`; when not editable show `<p className="text-sm text-slate-400 mb-3">Read only: shared with you by {ownerOf(selectedAccountObj)?.username}.</p>` above the list.
  - Settings tab: render `{user?.role === 'PARENT' && <ShareSettings />}` between `FamilyManager` and `DataManager`.
  - Tag dropdown first option text: `For: no child`.

- [ ] **Step 7: `DataManager.tsx` privacy rules** — replace the first `<li>` with two:

```tsx
                            <li>• Each parent's accounts and budgets are private unless shared in Settings → Sharing (view or manage)</li>
                            <li>• Shared costs, investments and yearly bills in the Common budget are visible to both parents</li>
```

- [ ] **Step 8: Verify** — `cd frontend && npm run lint && npm run type-check && npm run build`; Expected: all pass. Then start backend + Vite (see Task 12, Step 1) and check by hand: as a parent, Overview shows only own accounts; after the other parent shares "Can view", their accounts appear without edit buttons.

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): private parent finances with a sharing setting"
```

---

### Task 9: Frontend — Common tab and shared expenses

**Files:**
- Create: `frontend/src/finance.ts` (types and `money()`)
- Create: `frontend/src/components/SplitManager.tsx`
- Create: `frontend/src/components/CommonBudget.tsx`
- Modify: `frontend/src/pages/dashboard/Dashboard.tsx` (tab, "Shared" dropdown, shared badge)

**Interfaces:**
- Consumes: `/splits`, `/common/balance`, `/common/expenses`, `/common/overview`, `/settlements`, `/accounts`.
- Produces (`finance.ts`):
  ```ts
  export interface Split { id: string; name: string; shares: Record<string, number> }
  export interface Overview { items: { kind: 'planned' | 'asset'; id: string; name: string; monthly: number; shares: Record<string, number> }[]; totals: Record<string, number> }
  export function money(value: number): string
  export function useSplits(): { splits: Split[]; reload: () => void }
  ```

- [ ] **Step 1: `finance.ts`**

```ts
import { useCallback, useEffect, useState } from 'react';
import api from './api';

export interface Split {
    id: string;
    name: string;
    // Percent per parent id
    shares: Record<string, number>;
}

export interface Overview {
    items: { kind: 'planned' | 'asset'; id: string; name: string; monthly: number; shares: Record<string, number> }[];
    totals: Record<string, number>;
}

// Same money format as the rest of the app
export function money(value: number): string {
    return `$${value.toFixed(2)}`;
}

// The parents' preset splits (empty for children, who can't use them)
export function useSplits() {
    const [splits, setSplits] = useState<Split[]>([]);
    const [version, setVersion] = useState(0);

    useEffect(() => {
        api.get('/api/v1/splits')
            .then(response => setSplits(response.data))
            .catch(() => setSplits([]));
    }, [version]);

    const reload = useCallback(() => setVersion(v => v + 1), []);
    return { splits, reload };
}

export const describeSplit = (split: Split, nameOf: (id: string) => string) =>
    Object.entries(split.shares).map(([id, percent]) => `${nameOf(id)} ${percent}%`).join(' / ');
```

- [ ] **Step 2: `SplitManager.tsx`** — list splits with `describeSplit`; an inline form (name + one number input per active parent, live sum shown, Save disabled unless the sum is 100) for add (hidden at 4 splits) and edit; Delete with `confirm()`; show API errors (e.g. 409 "In use by …"). Code:

```tsx
import { useState } from 'react';
import api, { errorMessage } from '../api';
import { describeSplit, type Split } from '../finance';
import type { FamilyUser } from '../family';

interface Props {
    splits: Split[];
    parents: FamilyUser[];
    onChange: () => void;
}

const MAX_SPLITS = 4;

// The 2–4 preset ratios shared costs can use, e.g. "Equal" 50/50 or "By income" 70/30
export default function SplitManager({ splits, parents, onChange }: Props) {
    const [editing, setEditing] = useState<{ id: string | null; name: string; shares: Record<string, string> } | null>(null);
    const [error, setError] = useState('');
    const nameOf = (id: string) => parents.find(p => p.id === id)?.username ?? 'former parent';
    const total = editing ? parents.reduce((sum, p) => sum + (parseInt(editing.shares[p.id] || '0', 10) || 0), 0) : 0;

    const open = (split?: Split) => {
        setError('');
        setEditing({
            id: split?.id ?? null,
            name: split?.name ?? '',
            shares: Object.fromEntries(parents.map(p => [p.id, String(split?.shares[p.id] ?? Math.floor(100 / parents.length))]))
        });
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editing) return;
        const body = {
            name: editing.name,
            shares: Object.fromEntries(parents.map(p => [p.id, parseInt(editing.shares[p.id] || '0', 10)]))
        };
        try {
            if (editing.id) await api.put(`/api/v1/splits/${editing.id}`, body);
            else await api.post('/api/v1/splits', body);
            setEditing(null);
            onChange();
        } catch (err) {
            setError(errorMessage(err, 'Failed to save the split'));
        }
    };

    const remove = async (split: Split) => {
        if (!confirm(`Delete the split "${split.name}"?`)) return;
        try {
            await api.delete(`/api/v1/splits/${split.id}`);
            onChange();
        } catch (err) {
            setError(errorMessage(err, 'Failed to delete the split'));
        }
    };

    return (
        <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold">Splits</h2>
                {splits.length < MAX_SPLITS && !editing && (
                    <button onClick={() => open()} className="btn-primary text-sm">+ Add Split</button>
                )}
            </div>
            {error && <p className="mb-3 text-red-300">{error}</p>}
            <div className="space-y-2">
                {splits.map(split => (
                    <div key={split.id} className="p-3 bg-slate-800/30 rounded-lg flex flex-wrap justify-between gap-2">
                        <div>
                            <p className="font-semibold">{split.name}</p>
                            <p className="text-sm text-slate-400">{describeSplit(split, nameOf)}</p>
                        </div>
                        <div className="flex gap-3 text-sm">
                            <button onClick={() => open(split)} className="text-slate-400 hover:text-white">Edit</button>
                            <button onClick={() => remove(split)} className="text-slate-400 hover:text-red-400">Delete</button>
                        </div>
                    </div>
                ))}
                {splits.length === 0 && !editing && <p className="text-slate-400 text-sm">No splits yet. Add one, e.g. "Equal" 50/50.</p>}
            </div>
            {editing && (
                <form onSubmit={save} className="mt-4 p-4 bg-slate-800/30 rounded-lg space-y-3">
                    <input
                        type="text"
                        placeholder="Name, e.g. By income"
                        value={editing.name}
                        onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                        className="w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                        aria-label="Split name"
                        required
                    />
                    {parents.map(parent => (
                        <label key={parent.id} className="flex items-center justify-between gap-3">
                            <span>{parent.username}</span>
                            <span className="flex items-center gap-1">
                                <input
                                    type="number"
                                    min="0"
                                    max="100"
                                    step="1"
                                    value={editing.shares[parent.id]}
                                    onChange={(e) => setEditing({ ...editing, shares: { ...editing.shares, [parent.id]: e.target.value } })}
                                    className="w-20 p-2 rounded bg-slate-800/50 border border-slate-600 text-white text-right"
                                    aria-label={`${parent.username} percent`}
                                />
                                %
                            </span>
                        </label>
                    ))}
                    <p className={`text-sm ${total === 100 ? 'text-slate-400' : 'text-red-300'}`}>Total: {total}% (must be 100%)</p>
                    <div className="flex gap-2">
                        <button type="submit" className="btn-primary flex-1" disabled={total !== 100}>Save</button>
                        <button type="button" onClick={() => setEditing(null)} className="px-4 text-slate-400 hover:text-white">Cancel</button>
                    </div>
                </form>
            )}
        </div>
    );
}
```

- [ ] **Step 3: `CommonBudget.tsx`** — three cards plus `SplitManager`:

```tsx
import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { money, useSplits, type Overview } from '../finance';
import SplitManager from './SplitManager';

interface Balance { user_id: string; amount: number }
interface SharedExpense {
    transaction_id: string;
    date: string;
    description: string | null;
    amount: number;
    payer_id: string;
    split_name: string | null;
    shares: Record<string, number>;
}
interface Account { id: string; user_id: string; name: string }
interface Settlement { id: string; from_user_id: string; to_user_id: string; amount: number; date: string }

// Costs the parents share: who owes whom, each parent's monthly share, and the splits
export default function CommonBudget() {
    const { user } = useAuth();
    const { users } = useFamily();
    const { splits, reload: reloadSplits } = useSplits();
    const [balances, setBalances] = useState<Balance[]>([]);
    const [expenses, setExpenses] = useState<SharedExpense[]>([]);
    const [overview, setOverview] = useState<Overview>({ items: [], totals: {} });
    const [settlements, setSettlements] = useState<Settlement[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [settling, setSettling] = useState<{ amount: string; fromAccount: string; toAccount: string } | null>(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);
    const refresh = () => setVersion(v => v + 1);

    const parents = users.filter(u => u.role === 'PARENT' && u.is_active !== false);
    const nameOf = (id: string) => users.find(u => u.id === id)?.username ?? 'former parent';

    useEffect(() => {
        Promise.all([
            api.get('/api/v1/common/balance'),
            api.get('/api/v1/common/expenses'),
            api.get('/api/v1/common/overview'),
            api.get('/api/v1/settlements'),
            api.get('/api/v1/accounts')
        ])
            .then(([b, e, o, s, a]) => {
                setBalances(b.data);
                setExpenses(e.data);
                setOverview(o.data);
                setSettlements(s.data);
                setAccounts(a.data);
            })
            .catch(err => setError(errorMessage(err, 'Failed to load the common budget')));
    }, [version, splits]);

    // With two parents the balance is one number: who owes whom
    const debtor = balances.find(b => b.amount < 0);
    const creditor = balances.find(b => b.amount > 0);
    const owed = creditor ? creditor.amount : 0;
    // Only accounts the current user can see can be chosen; each parent settles from/to their own
    const accountsOf = (userId?: string) => accounts.filter(a => a.user_id === userId);

    const settle = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!settling || !debtor || !creditor) return;
        try {
            await api.post('/api/v1/settlements', {
                from_user_id: debtor.user_id,
                to_user_id: creditor.user_id,
                amount: parseFloat(settling.amount),
                from_account_id: settling.fromAccount,
                to_account_id: settling.toAccount
            });
            setSettling(null);
            refresh();
        } catch (err) {
            setError(errorMessage(err, 'Failed to settle up'));
        }
    };

    const undoSettlement = async (settlement: Settlement) => {
        if (!confirm(`Undo the payment of ${money(settlement.amount)}? Both transfer transactions are removed.`)) return;
        try {
            await api.delete(`/api/v1/settlements/${settlement.id}`);
            refresh();
        } catch (err) {
            setError(errorMessage(err, 'Failed to undo'));
        }
    };

    if (parents.length < 2) {
        return (
            <div className="glass-card p-6">
                <h2 className="text-2xl font-bold mb-2">Common budget</h2>
                <p className="text-slate-400">Sharing costs needs a second parent. Add one in Settings → Family.</p>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {error && (
                <div className="p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between">
                    <span>{error}</span>
                    <button onClick={() => setError('')} aria-label="Dismiss error">✕</button>
                </div>
            )}

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-2">Balance</h2>
                {owed > 0 && debtor && creditor ? (
                    <p className="text-2xl font-bold">
                        {debtor.user_id === user?.id ? 'You owe' : `${nameOf(debtor.user_id)} owes`}{' '}
                        {creditor.user_id === user?.id ? 'you' : nameOf(creditor.user_id)} {money(owed)}
                    </p>
                ) : (
                    <p className="text-2xl font-bold text-emerald-400">All settled</p>
                )}
                {owed > 0 && !settling && (
                    <button
                        onClick={() => setSettling({
                            amount: owed.toFixed(2),
                            fromAccount: accountsOf(debtor?.user_id)[0]?.id ?? '',
                            toAccount: accountsOf(creditor?.user_id)[0]?.id ?? ''
                        })}
                        className="btn-primary text-sm mt-3"
                    >
                        Settle up
                    </button>
                )}
                {settling && debtor && creditor && (
                    <form onSubmit={settle} className="mt-4 p-4 bg-slate-800/30 rounded-lg space-y-2">
                        <input
                            type="number" step="0.01" min="0.01"
                            value={settling.amount}
                            onChange={(e) => setSettling({ ...settling, amount: e.target.value })}
                            className="w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                            aria-label="Amount"
                            required
                        />
                        {[
                            { key: 'fromAccount' as const, owner: debtor.user_id, label: `From ${nameOf(debtor.user_id)}'s account` },
                            { key: 'toAccount' as const, owner: creditor.user_id, label: `To ${nameOf(creditor.user_id)}'s account` }
                        ].map(field => (
                            <select
                                key={field.key}
                                value={settling[field.key]}
                                onChange={(e) => setSettling({ ...settling, [field.key]: e.target.value })}
                                className="w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                aria-label={field.label}
                                required
                            >
                                <option value="">{field.label}</option>
                                {accountsOf(field.owner).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                            </select>
                        ))}
                        <p className="text-xs text-slate-500">
                            Only accounts you can see are listed. If the other parent's accounts are missing, they can settle up
                            themselves, or share their finances with you.
                        </p>
                        <div className="flex gap-2">
                            <button type="submit" className="btn-primary flex-1">Record payment</button>
                            <button type="button" onClick={() => setSettling(null)} className="px-4 text-slate-400 hover:text-white">Cancel</button>
                        </div>
                    </form>
                )}
                {settlements.length > 0 && (
                    <div className="mt-4 space-y-1 text-sm text-slate-400">
                        {settlements.slice(0, 5).map(s => (
                            <div key={s.id} className="flex justify-between">
                                <span>{new Date(s.date).toLocaleDateString()}: {nameOf(s.from_user_id)} paid {nameOf(s.to_user_id)} {money(s.amount)}</span>
                                <button onClick={() => undoSettlement(s)} className="hover:text-red-400">Undo</button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-1">Monthly shares</h2>
                <p className="text-sm text-slate-400 mb-4">Common monthly costs, yearly bills (÷ 12) and investments (set-aside), divided by their split.</p>
                {overview.items.length === 0 ? (
                    <p className="text-slate-400 text-sm">Nothing planned yet. Add common yearly bills or investments in their tabs.</p>
                ) : (
                    <div className="space-y-1">
                        {overview.items.map(item => (
                            <div key={item.id} className="flex justify-between p-2 bg-slate-800/30 rounded">
                                <span>{item.kind === 'asset' ? '📦 ' : ''}{item.name}</span>
                                <span>{money(item.monthly)}/month</span>
                            </div>
                        ))}
                        <div className="flex flex-wrap gap-4 pt-3 font-bold">
                            {parents.map(p => (
                                <span key={p.id}>{p.id === user?.id ? 'You' : p.username}: {money(overview.totals[p.id] ?? 0)}/month</span>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            <div className="glass-card p-6">
                <h2 className="text-xl font-bold mb-4">Shared expenses</h2>
                {expenses.length === 0 ? (
                    <p className="text-slate-400 text-sm">No shared expenses yet. When you add an expense, choose a split under "Shared".</p>
                ) : (
                    <div className="space-y-2">
                        {expenses.slice(0, 30).map(e => (
                            <div key={e.transaction_id} className="p-3 bg-slate-800/30 rounded-lg flex flex-wrap justify-between gap-2">
                                <div>
                                    <p className="font-semibold">{e.description || 'No description'}</p>
                                    <p className="text-sm text-slate-400">
                                        {new Date(e.date).toLocaleDateString()} · paid by {nameOf(e.payer_id)} · {e.split_name ?? 'deleted split'}
                                    </p>
                                </div>
                                <div className="text-right">
                                    <p className="font-bold">{money(e.amount)}</p>
                                    <p className="text-xs text-slate-400">
                                        {Object.entries(e.shares).map(([id, amount]) => `${nameOf(id)} ${money(amount)}`).join(' · ')}
                                    </p>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <SplitManager splits={splits} parents={parents} onChange={() => { reloadSplits(); refresh(); }} />
        </div>
    );
}
```

- [ ] **Step 4: `Dashboard.tsx` — tab and "Shared" field**
  - Import `CommonBudget` and `useSplits`; `const { splits } = useSplits();`.
  - Tabs: build the list depending on the role:

```ts
    const isParent = user?.role === 'PARENT';
    const tabs = [
        { id: 'overview', label: '📊 Overview' },
        { id: 'budgets', label: '💰 Budgets' },
        ...(isParent ? [{ id: 'common', label: '🤝 Common' }] : []),
        { id: 'analytics', label: '📈 Analytics' },
        { id: 'settings', label: '⚙️ Settings' }
    ];
```

    and render `{activeTab === 'common' && <CommonBudget />}`.
  - Transaction state gets `split_id: ''` (in the initial state, `closeTransactionForm` reset and `handleEditTransaction` with `transaction.split_id || ''`); add `split_id?: string | null;` to the `Transaction` interface.
  - Submit: add `split_id: newTransaction.split_id || null` to `fields`.
  - Form: after the child-tag select, when `isParent && selectedAccountObj && isParentAccount(selectedAccountObj) && splits.length > 0 && expenseCategories.some(c => c.id === newTransaction.category_id)`:

```tsx
                                        <select
                                            value={newTransaction.split_id}
                                            onChange={(e) => setNewTransaction({ ...newTransaction, split_id: e.target.value })}
                                            className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                            aria-label="Shared"
                                        >
                                            <option value="">Shared: not shared</option>
                                            {splits.map(split => (
                                                <option key={split.id} value={split.id}>Shared: {split.name}</option>
                                            ))}
                                        </select>
```

    Also when the category changes to an income, clear `split_id` (in the category `onChange`: `split_id: expenseCategories.some(c => c.id === e.target.value) ? newTransaction.split_id : ''`).
  - Transaction row: next to the child badge, `{transaction.split_id && <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300">shared</span>}`.
  - Transfers can't be edited or deleted here: hide ✎/✕ for transactions whose category type is `TRANSFER` (`categories.find(c => c.id === transaction.category_id)?.type === 'TRANSFER'`), and leave TRANSFER categories out of the category dropdown (it only lists INCOME and EXPENSE already).
  - Tab bar: make it scroll on a phone — `<div className="flex gap-2 overflow-x-auto">` and add `whitespace-nowrap` to each tab button's classes.

- [ ] **Step 5: Verify** — `cd frontend && npm run lint && npm run type-check && npm run build`; Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): common budget tab with splits, balance and settling up"
```

---

### Task 10: Frontend — Investments tab and "For item"

**Files:**
- Modify: `frontend/src/finance.ts` (`Asset`, `useAssets`)
- Create: `frontend/src/components/Investments.tsx`
- Create: `frontend/src/components/OwnerSelect.tsx` (shared with Task 11)
- Modify: `frontend/src/pages/dashboard/Dashboard.tsx`

**Interfaces:**
- Consumes: `/assets`, `/assets/{id}`, `useSplits`, `useFamily`.
- Produces:
  ```ts
  // finance.ts
  export interface Asset { id: string; name: string; price: number; purchase_date: string; lifespan_years: number;
      owner_id: string | null; split_id: string | null; notes: string | null; age_years: number; replacement_due: string;
      is_due: boolean; monthly_set_aside: number; total_cost: number; cost_per_year: number; shares: Record<string, number> }
  export function useAssets(): { assets: Asset[]; reload: () => void }
  // OwnerSelect.tsx: value is "owner:<userId>" or "split:<splitId>"
  export default function OwnerSelect(props: { value: string; onChange: (value: string) => void }): JSX.Element
  export function ownerFields(value: string): { owner_id: string | null; split_id: string | null }
  export function ownerValue(item: { owner_id: string | null; split_id: string | null }): string
  ```

- [ ] **Step 1: `finance.ts`** — append the `Asset` interface above and:

```ts
// Investments the current parent can see (empty for children)
export function useAssets() {
    const [assets, setAssets] = useState<Asset[]>([]);
    const [version, setVersion] = useState(0);

    useEffect(() => {
        api.get('/api/v1/assets')
            .then(response => setAssets(response.data))
            .catch(() => setAssets([]));
    }, [version]);

    const reload = useCallback(() => setVersion(v => v + 1), []);
    return { assets, reload };
}
```

- [ ] **Step 2: `OwnerSelect.tsx`**

```tsx
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { accessTo } from '../family';
import { useSplits } from '../finance';

export function ownerFields(value: string): { owner_id: string | null; split_id: string | null } {
    const [kind, id] = value.split(':');
    return kind === 'split' ? { owner_id: null, split_id: id } : { owner_id: id, split_id: null };
}

export function ownerValue(item: { owner_id: string | null; split_id: string | null }): string {
    return item.split_id ? `split:${item.split_id}` : `owner:${item.owner_id}`;
}

// Who an investment or bill belongs to: me, a parent who shared with edit access, or common with a split
export default function OwnerSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
    const { user } = useAuth();
    const { users, shares } = useFamily();
    const { splits } = useSplits();
    const editableParents = users.filter(u =>
        u.role === 'PARENT' && u.id !== user?.id && user && accessTo(user, u.id, users, shares) === 'EDIT'
    );

    return (
        <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
            aria-label="Belongs to"
        >
            <option value={`owner:${user?.id}`}>Mine</option>
            {editableParents.map(p => <option key={p.id} value={`owner:${p.id}`}>{p.username}'s</option>)}
            {splits.map(split => <option key={split.id} value={`split:${split.id}`}>Common: {split.name}</option>)}
        </select>
    );
}
```

- [ ] **Step 3: `Investments.tsx`**

```tsx
import { useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { money, useAssets, useSplits, type Asset } from '../finance';
import OwnerSelect, { ownerFields, ownerValue } from './OwnerSelect';

interface Expense { id: string; amount: number; date: string; description: string | null }
type Filter = 'all' | 'mine' | 'common' | 'others';

const emptyForm = (userId: string) => ({
    id: null as string | null, name: '', price: '', purchase_date: new Date().toISOString().slice(0, 10),
    lifespan_years: '5', owner: `owner:${userId}`, notes: ''
});

// Big purchases (TV, fridge, car, bike): age, when to replace them, what to set aside, and what they cost so far
export default function Investments() {
    const { user } = useAuth();
    const { users } = useFamily();
    const { splits } = useSplits();
    const { assets, reload } = useAssets();
    const [filter, setFilter] = useState<Filter>('all');
    const [form, setForm] = useState<ReturnType<typeof emptyForm> | null>(null);
    const [openId, setOpenId] = useState<string | null>(null);
    const [expenses, setExpenses] = useState<Expense[]>([]);
    const [error, setError] = useState('');

    const ownerLabel = (asset: Asset) => {
        if (asset.split_id) return `Common · ${splits.find(s => s.id === asset.split_id)?.name ?? 'split'}`;
        return asset.owner_id === user?.id ? 'Mine' : `${users.find(u => u.id === asset.owner_id)?.username ?? ''}'s`;
    };
    const shown = assets.filter(a =>
        filter === 'all' ||
        (filter === 'mine' && a.owner_id === user?.id) ||
        (filter === 'common' && a.split_id) ||
        (filter === 'others' && a.owner_id && a.owner_id !== user?.id)
    );

    const toggle = async (asset: Asset) => {
        if (openId === asset.id) { setOpenId(null); return; }
        try {
            const response = await api.get(`/api/v1/assets/${asset.id}`);
            setExpenses(response.data.expenses);
            setOpenId(asset.id);
        } catch (err) {
            setError(errorMessage(err, 'Failed to load the investment'));
        }
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form) return;
        const body = {
            name: form.name, price: parseFloat(form.price), purchase_date: form.purchase_date,
            lifespan_years: parseInt(form.lifespan_years, 10), notes: form.notes || null, ...ownerFields(form.owner)
        };
        try {
            if (form.id) await api.put(`/api/v1/assets/${form.id}`, body);
            else await api.post('/api/v1/assets', body);
            setForm(null);
            reload();
        } catch (err) {
            setError(errorMessage(err, 'Failed to save the investment'));
        }
    };

    const remove = async (asset: Asset) => {
        if (!confirm(`Delete "${asset.name}"? Its linked expenses stay as normal expenses.`)) return;
        try {
            await api.delete(`/api/v1/assets/${asset.id}`);
            reload();
        } catch (err) {
            setError(errorMessage(err, 'Failed to delete the investment'));
        }
    };

    const edit = (asset: Asset) => setForm({
        id: asset.id, name: asset.name, price: String(asset.price), purchase_date: asset.purchase_date,
        lifespan_years: String(asset.lifespan_years), owner: ownerValue(asset), notes: asset.notes ?? ''
    });

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="space-y-6">
            <div className="glass-card p-6">
                <div className="flex flex-wrap justify-between items-center gap-3 mb-4">
                    <h2 className="text-2xl font-bold">Investments</h2>
                    <div className="flex gap-3">
                        <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white" aria-label="Show">
                            <option value="all">All</option>
                            <option value="mine">Mine</option>
                            <option value="common">Common</option>
                            <option value="others">Shared with me</option>
                        </select>
                        {!form && user && <button onClick={() => setForm(emptyForm(user.id))} className="btn-primary text-sm">+ Add Item</button>}
                    </div>
                </div>
                <p className="text-sm text-slate-400 mb-4">
                    Link repairs, service or tyres to an item with "For item" when you add the expense.
                </p>
                {error && <p className="mb-3 text-red-300">{error}</p>}

                {form && (
                    <form onSubmit={save} className="mb-6 p-4 bg-slate-800/30 rounded-lg grid gap-2 md:grid-cols-2">
                        <input className={input} placeholder="Name, e.g. Car" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="Name" required />
                        <input className={input} type="number" step="0.01" min="0.01" placeholder="Price" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} aria-label="Price" required />
                        <label className="text-sm text-slate-400">Bought on
                            <input className={input} type="date" value={form.purchase_date} onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} required />
                        </label>
                        <label className="text-sm text-slate-400">Expected to last (years)
                            <input className={input} type="number" min="1" max="100" step="1" value={form.lifespan_years} onChange={(e) => setForm({ ...form, lifespan_years: e.target.value })} required />
                        </label>
                        <OwnerSelect value={form.owner} onChange={(owner) => setForm({ ...form, owner })} />
                        <input className={input} placeholder="Notes (warranty, serial number, ...)" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} aria-label="Notes" />
                        <div className="flex gap-2 md:col-span-2">
                            <button type="submit" className="btn-primary flex-1">{form.id ? 'Save' : 'Add Item'}</button>
                            <button type="button" onClick={() => setForm(null)} className="px-4 text-slate-400 hover:text-white">Cancel</button>
                        </div>
                    </form>
                )}

                {shown.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">No investments yet</p>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {shown.map(asset => {
                            const used = Math.min(asset.age_years / asset.lifespan_years, 1);
                            return (
                                <div key={asset.id} className="p-4 rounded-lg bg-slate-800/30 border border-slate-700">
                                    <div className="flex justify-between gap-2">
                                        <h3 className="font-semibold text-lg">{asset.name}</h3>
                                        {asset.is_due && <span className="text-xs px-2 py-0.5 h-fit rounded-full bg-amber-500/20 text-amber-300">Due</span>}
                                    </div>
                                    <p className="text-xs text-slate-500">{ownerLabel(asset)}</p>
                                    <div className="mt-3 h-2 rounded bg-slate-700" aria-label={`${asset.age_years} of ${asset.lifespan_years} years`}>
                                        <div className={`h-2 rounded ${asset.is_due ? 'bg-amber-400' : 'bg-cyan-400'}`} style={{ width: `${used * 100}%` }} />
                                    </div>
                                    <p className="text-sm text-slate-400 mt-1">{asset.age_years} of {asset.lifespan_years} years · replace {new Date(asset.replacement_due).getFullYear()}</p>
                                    <p className="mt-2">Set aside <strong>{money(asset.monthly_set_aside)}</strong>/month</p>
                                    <div className="flex gap-3 mt-3 text-sm">
                                        <button onClick={() => toggle(asset)} className="text-slate-400 hover:text-white">{openId === asset.id ? 'Hide costs' : 'Costs'}</button>
                                        <button onClick={() => edit(asset)} className="text-slate-400 hover:text-white">Edit</button>
                                        <button onClick={() => remove(asset)} className="text-slate-400 hover:text-red-400">Delete</button>
                                    </div>
                                    {openId === asset.id && (
                                        <div className="mt-3 pt-3 border-t border-slate-700 text-sm space-y-1">
                                            <p>Bought for {money(asset.price)} on {new Date(asset.purchase_date).toLocaleDateString()}</p>
                                            {expenses.map(e => (
                                                <p key={e.id} className="text-slate-400">{new Date(e.date).toLocaleDateString()} · {e.description || 'No description'} · {money(Math.abs(e.amount))}</p>
                                            ))}
                                            <p className="font-semibold">Total {money(asset.total_cost)} · {money(asset.cost_per_year)}/year</p>
                                            {asset.notes && <p className="text-slate-400">📝 {asset.notes}</p>}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
```

(Edit/Delete buttons on items the user can only view return 404 from the API; hide them for `asset.owner_id && asset.owner_id !== user?.id && accessTo(...) !== 'EDIT'` using `accessTo` and `shares` from `useFamily` — add that check as `const canChange = (a: Asset) => !a.owner_id || (user && ['OWN', 'EDIT'].includes(accessTo(user, a.owner_id, users, shares) ?? ''));` and wrap both buttons in `{canChange(asset) && (...)}`.)

- [ ] **Step 4: `Dashboard.tsx` — tab and "For item"**
  - Tabs: after Common add `...(isParent ? [{ id: 'investments', label: '📦 Investments' }] : [])`; render `{activeTab === 'investments' && <Investments />}`.
  - `const { assets } = useAssets();` (import from `../../finance`).
  - Transaction state gets `asset_id: ''` (initial, reset, edit with `transaction.asset_id || ''`); interface gets `asset_id?: string | null;`; submit adds `asset_id: newTransaction.asset_id || null`.
  - Form, for parents when the category is an expense and `assets.length > 0`:

```tsx
                                        <select
                                            value={newTransaction.asset_id}
                                            onChange={(e) => setNewTransaction({ ...newTransaction, asset_id: e.target.value })}
                                            className="w-full mb-2 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                            aria-label="For item"
                                        >
                                            <option value="">For item: none</option>
                                            {assets.map(asset => <option key={asset.id} value={asset.id}>For item: {asset.name}</option>)}
                                        </select>
```

  - Row badge: `{assetName(transaction.asset_id) && <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">{assetName(transaction.asset_id)}</span>}` with `const assetName = (id?: string | null) => assets.find(a => a.id === id)?.name;`.

- [ ] **Step 5: Verify and commit**

```bash
cd frontend && npm run lint && npm run type-check && npm run build && cd ..
git add frontend/src
git commit -m "feat(frontend): investments tab with replacement planning and linked costs"
```

---

### Task 11: Frontend — Yearly bills tab

**Files:**
- Modify: `frontend/src/finance.ts` (`PlannedCost`)
- Create: `frontend/src/components/YearlyBills.tsx`
- Create: `frontend/src/components/MonthlyCosts.tsx` (common monthly costs, shown in the Common tab)
- Modify: `frontend/src/components/CommonBudget.tsx`, `frontend/src/pages/dashboard/Dashboard.tsx`

**Interfaces:**
- Consumes: `/planned-costs`, `OwnerSelect`, `ownerFields`, `ownerValue`, `useSplits`, `money`.
- Produces: `finance.ts`
  ```ts
  export interface PlannedCost { id: string; name: string; category_id: string; amount: number; frequency: 'MONTHLY' | 'YEARLY';
      due_month: number | null; owner_id: string | null; split_id: string | null; notes: string | null;
      monthly: number; next_due: string | null; due_soon: boolean; shares: Record<string, number> }
  ```

- [ ] **Step 1: Add the `PlannedCost` interface** to `finance.ts`, plus
`export const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];`

- [ ] **Step 2: `YearlyBills.tsx`**

```tsx
import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { accessTo } from '../family';
import { MONTHS, money, useSplits, type PlannedCost } from '../finance';
import OwnerSelect, { ownerFields, ownerValue } from './OwnerSelect';

interface Category { id: string; name: string; type: string }

const emptyForm = (userId: string) => ({
    id: null as string | null, name: '', category_id: '', amount: '', due_month: String(new Date().getMonth() + 1),
    owner: `owner:${userId}`, notes: ''
});

// Bills that come once a year: what's due soon, the yearly total and what to put aside each month
export default function YearlyBills() {
    const { user } = useAuth();
    const { users, shares } = useFamily();
    const { splits } = useSplits();
    const [bills, setBills] = useState<PlannedCost[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [form, setForm] = useState<ReturnType<typeof emptyForm> | null>(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);

    useEffect(() => {
        Promise.all([api.get('/api/v1/planned-costs', { params: { frequency: 'YEARLY' } }), api.get('/api/v1/categories')])
            .then(([b, c]) => {
                setBills(b.data);
                setCategories(c.data.filter((cat: Category) => cat.type === 'EXPENSE'));
            })
            .catch(err => setError(errorMessage(err, 'Failed to load yearly bills')));
    }, [version]);

    const nameOf = (id: string) => (id === user?.id ? 'You' : users.find(u => u.id === id)?.username ?? '');
    const canChange = (bill: PlannedCost) =>
        !bill.owner_id || (!!user && ['OWN', 'EDIT'].includes(accessTo(user, bill.owner_id, users, shares) ?? ''));
    const yearly = bills.reduce((sum, b) => sum + b.amount, 0);
    // Per person: your own bills plus your part of common ones
    const perPerson: Record<string, number> = {};
    bills.forEach(b => Object.entries(b.shares).forEach(([id, amount]) => { perPerson[id] = (perPerson[id] ?? 0) + amount; }));

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form) return;
        const body = {
            name: form.name, category_id: form.category_id, amount: parseFloat(form.amount), frequency: 'YEARLY',
            due_month: parseInt(form.due_month, 10), notes: form.notes || null, ...ownerFields(form.owner)
        };
        try {
            if (form.id) await api.put(`/api/v1/planned-costs/${form.id}`, body);
            else await api.post('/api/v1/planned-costs', body);
            setForm(null);
            setVersion(v => v + 1);
        } catch (err) {
            setError(errorMessage(err, 'Failed to save the bill'));
        }
    };

    const remove = async (bill: PlannedCost) => {
        if (!confirm(`Delete the yearly bill "${bill.name}"?`)) return;
        try {
            await api.delete(`/api/v1/planned-costs/${bill.id}`);
            setVersion(v => v + 1);
        } catch (err) {
            setError(errorMessage(err, 'Failed to delete the bill'));
        }
    };

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="glass-card p-6">
                    <h3 className="text-sky-400 text-lg font-semibold mb-2">Per year</h3>
                    <p className="text-3xl font-bold">{money(yearly)}</p>
                </div>
                <div className="glass-card p-6">
                    <h3 className="text-emerald-400 text-lg font-semibold mb-2">Put aside per month</h3>
                    {Object.keys(perPerson).length === 0 ? <p className="text-3xl font-bold">{money(0)}</p> : (
                        Object.entries(perPerson).map(([id, amount]) => (
                            <p key={id} className="text-xl font-bold">{nameOf(id)}: {money(amount)}</p>
                        ))
                    )}
                </div>
            </div>

            <div className="glass-card p-6">
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-2xl font-bold">Yearly bills</h2>
                    {!form && user && <button onClick={() => setForm(emptyForm(user.id))} className="btn-primary text-sm">+ Add Bill</button>}
                </div>
                {error && <p className="mb-3 text-red-300">{error}</p>}

                {form && (
                    <form onSubmit={save} className="mb-6 p-4 bg-slate-800/30 rounded-lg grid gap-2 md:grid-cols-2">
                        <input className={input} placeholder="Name, e.g. Water" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="Name" required />
                        <input className={input} type="number" step="0.01" min="0.01" placeholder="Amount per year" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} aria-label="Amount per year" required />
                        <select className={input} value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })} aria-label="Category" required>
                            <option value="">Select Category</option>
                            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                        <select className={input} value={form.due_month} onChange={(e) => setForm({ ...form, due_month: e.target.value })} aria-label="Due month">
                            {MONTHS.map((month, i) => <option key={month} value={i + 1}>Due in {month}</option>)}
                        </select>
                        <OwnerSelect value={form.owner} onChange={(owner) => setForm({ ...form, owner })} />
                        <input className={input} placeholder="Notes (customer number, ...)" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} aria-label="Notes" />
                        <div className="flex gap-2 md:col-span-2">
                            <button type="submit" className="btn-primary flex-1">{form.id ? 'Save' : 'Add Bill'}</button>
                            <button type="button" onClick={() => setForm(null)} className="px-4 text-slate-400 hover:text-white">Cancel</button>
                        </div>
                    </form>
                )}

                {bills.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">No yearly bills yet</p>
                ) : (
                    <div className="space-y-2">
                        {bills.map(bill => (
                            <div key={bill.id} className={`p-3 rounded-lg flex flex-wrap justify-between gap-2 ${bill.due_soon ? 'bg-amber-500/10 border border-amber-500/40' : 'bg-slate-800/30'}`}>
                                <div>
                                    <p className="font-semibold">
                                        {bill.name}
                                        {bill.due_soon && <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">due soon</span>}
                                    </p>
                                    <p className="text-sm text-slate-400">
                                        Due {bill.next_due && new Date(bill.next_due).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
                                        {' · '}{bill.split_id ? `Common · ${splits.find(s => s.id === bill.split_id)?.name ?? 'split'}` : nameOf(bill.owner_id!)}
                                    </p>
                                </div>
                                <div className="flex items-center gap-3">
                                    <div className="text-right">
                                        <p className="font-bold">{money(bill.amount)}</p>
                                        <p className="text-xs text-slate-400">{money(bill.monthly)}/month</p>
                                    </div>
                                    {canChange(bill) && (<>
                                        <button onClick={() => setForm({ id: bill.id, name: bill.name, category_id: bill.category_id, amount: String(bill.amount), due_month: String(bill.due_month), owner: ownerValue(bill), notes: bill.notes ?? '' })} className="text-slate-500 hover:text-blue-400" aria-label="Edit bill">✎</button>
                                        <button onClick={() => remove(bill)} className="text-slate-500 hover:text-red-400" aria-label="Delete bill">✕</button>
                                    </>)}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
```

- [ ] **Step 3: `MonthlyCosts.tsx`** — common monthly costs (rent, health insurance per month, ...) managed in the Common tab, since monthly planned costs are always common:

```tsx
import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import { money, type PlannedCost, type Split } from '../finance';

interface Category { id: string; name: string; type: string }

// Common costs that come every month; they count in the monthly shares above
export default function MonthlyCosts({ splits, onChange }: { splits: Split[]; onChange: () => void }) {
    const [costs, setCosts] = useState<PlannedCost[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [form, setForm] = useState<{ id: string | null; name: string; category_id: string; amount: string; split_id: string } | null>(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);

    useEffect(() => {
        Promise.all([api.get('/api/v1/planned-costs', { params: { frequency: 'MONTHLY' } }), api.get('/api/v1/categories')])
            .then(([c, cats]) => {
                setCosts(c.data);
                setCategories(cats.data.filter((cat: Category) => cat.type === 'EXPENSE'));
            })
            .catch(err => setError(errorMessage(err, 'Failed to load monthly costs')));
    }, [version]);

    const changed = () => { setVersion(v => v + 1); onChange(); };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form) return;
        const body = { name: form.name, category_id: form.category_id, amount: parseFloat(form.amount), frequency: 'MONTHLY', split_id: form.split_id, owner_id: null };
        try {
            if (form.id) await api.put(`/api/v1/planned-costs/${form.id}`, body);
            else await api.post('/api/v1/planned-costs', body);
            setForm(null);
            changed();
        } catch (err) {
            setError(errorMessage(err, 'Failed to save the cost'));
        }
    };

    const remove = async (cost: PlannedCost) => {
        if (!confirm(`Delete "${cost.name}"?`)) return;
        try {
            await api.delete(`/api/v1/planned-costs/${cost.id}`);
            changed();
        } catch (err) {
            setError(errorMessage(err, 'Failed to delete the cost'));
        }
    };

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold">Monthly common costs</h2>
                {!form && splits.length > 0 && (
                    <button onClick={() => setForm({ id: null, name: '', category_id: '', amount: '', split_id: splits[0].id })} className="btn-primary text-sm">+ Add Cost</button>
                )}
            </div>
            {splits.length === 0 && <p className="text-slate-400 text-sm">Add a split first.</p>}
            {error && <p className="mb-3 text-red-300">{error}</p>}
            {form && (
                <form onSubmit={save} className="mb-4 p-4 bg-slate-800/30 rounded-lg grid gap-2 md:grid-cols-2">
                    <input className={input} placeholder="Name, e.g. Rent" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="Name" required />
                    <input className={input} type="number" step="0.01" min="0.01" placeholder="Amount per month" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} aria-label="Amount per month" required />
                    <select className={input} value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })} aria-label="Category" required>
                        <option value="">Select Category</option>
                        {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                    <select className={input} value={form.split_id} onChange={(e) => setForm({ ...form, split_id: e.target.value })} aria-label="Split">
                        {splits.map(s => <option key={s.id} value={s.id}>Split: {s.name}</option>)}
                    </select>
                    <div className="flex gap-2 md:col-span-2">
                        <button type="submit" className="btn-primary flex-1">{form.id ? 'Save' : 'Add Cost'}</button>
                        <button type="button" onClick={() => setForm(null)} className="px-4 text-slate-400 hover:text-white">Cancel</button>
                    </div>
                </form>
            )}
            <div className="space-y-2">
                {costs.map(cost => (
                    <div key={cost.id} className="p-3 bg-slate-800/30 rounded-lg flex justify-between items-center gap-2">
                        <div>
                            <p className="font-semibold">{cost.name}</p>
                            <p className="text-sm text-slate-400">{splits.find(s => s.id === cost.split_id)?.name ?? 'split'}</p>
                        </div>
                        <div className="flex items-center gap-3">
                            <p className="font-bold">{money(cost.amount)}/month</p>
                            <button onClick={() => setForm({ id: cost.id, name: cost.name, category_id: cost.category_id, amount: String(cost.amount), split_id: cost.split_id! })} className="text-slate-500 hover:text-blue-400" aria-label="Edit cost">✎</button>
                            <button onClick={() => remove(cost)} className="text-slate-500 hover:text-red-400" aria-label="Delete cost">✕</button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
```

In `CommonBudget.tsx`, render `<MonthlyCosts splits={splits} onChange={refresh} />` between the "Monthly shares" card and "Shared expenses".

- [ ] **Step 4: `Dashboard.tsx`** — add `...(isParent ? [{ id: 'bills', label: '🧾 Yearly bills' }] : [])` after Investments and render `{activeTab === 'bills' && <YearlyBills />}`.

- [ ] **Step 5: Verify and commit**

```bash
cd frontend && npm run lint && npm run type-check && npm run build && cd ..
git add frontend/src
git commit -m "feat(frontend): yearly bills tab and common monthly costs"
```

---

### Task 12: Smoke test, browser test, docs

**Files:**
- Modify: `tests/smoke_test.py`
- Create: `$S/e2e/common.js` (scratch, not committed)
- Modify: `README_DOCKER.md` (First login: mention sharing), memory files

- [ ] **Step 1: Smoke test** — in `tests/smoke_test.py` `main`, after "balance updated", add a second parent, a split and a shared expense:

```python
    status, _ = call(base_url, "POST", "/users", {"username": f"{username}_b", "pin": "1234", "role": "PARENT"}, token)
    check("add a second parent", status == 200)
    status, users = call(base_url, "GET", "/users", token=token)
    parent_ids = [u["id"] for u in users if u["role"] == "PARENT" and u["is_active"]]
    status, split = call(
        base_url, "POST", "/splits",
        {"name": f"Equal {username}", "shares": {pid: 100 // len(parent_ids) + (100 % len(parent_ids) if i == 0 else 0)
                                                 for i, pid in enumerate(parent_ids)}},
        token,
    )
    check("create a split", status == 200)
    status, _ = call(
        base_url, "POST", "/transactions",
        {"account_id": account["id"], "category_id": groceries, "amount": 30, "split_id": split["id"]}, token,
    )
    check("add a shared expense", status == 200)
    status, balances = call(base_url, "GET", "/common/balance", token=token)
    me = next(u["id"] for u in users if u["username"] == username)
    check("common balance counts the shared expense", status == 200 and next(b["amount"] for b in balances if b["user_id"] == me) > 0)
```

Run it against a local backend:

```bash
pid=$(ss -ltnp | grep ":8000 " | grep -o "pid=[0-9]*" | cut -d= -f2); [ -n "$pid" ] && kill $pid
rm -f $S/e2e.db
(cd backend && INITIAL_ADMIN_PIN=1111 DATABASE_URL="sqlite:///$S/e2e.db" setsid $S/venv/bin/uvicorn app.main:app --port 8000 > $S/backend.log 2>&1 < /dev/null &)
sleep 3 && python3 tests/smoke_test.py http://localhost:8000 1111
```

Expected: every line `ok`.

- [ ] **Step 2: Browser flow** — write `$S/e2e/common.js` (Puppeteer, same setup as `$S/e2e/rename.js`: new tab per login) that, with the Vite dev server on :3000 and the backend from Step 1 (fresh DB, Admin PIN 1111):
  1. logs in as Admin, adds parent "Mum" (PIN 2222) in Settings → Family;
  2. Common tab: adds split "Equal" 50/50; checks "All settled";
  3. Overview: creates account "Admin bank", adds a Groceries expense 100 with "Shared: Equal"; Common tab shows "Mum owes you $50.00";
  4. logs in as Mum in a new tab: Overview shows no "Admin bank"; Common tab shows "You owe Admin $50.00"; Settings → Sharing: no change;
  5. as Admin: Settings → Sharing "Can view" for Mum; as Mum: "Admin bank" appears with "Read only";
  6. as Admin: Investments → add "Car" 24000, bought 4 years ago, 8 years, Common: Equal → card shows "Set aside $250.00/month"; Yearly bills → add "Water" 600 due next month, Common: Equal → marked "due soon"; Common tab "Monthly shares" lists Car and Water;
  7. collects `pageerror`s and fails if any.

Run: `cd $S/e2e && timeout 180 node common.js $S`. Expected: every check prints `true`, no page errors. Also re-run `flow.js` and `rename.js` (update `flow.js` expectations that relied on "Household Balance" → "My Balance").

- [ ] **Step 3: Docs** — in `README_DOCKER.md` "First login", add after the family sentence:
  "Each parent's money is private. To let the other parent see or manage it, use **Settings → Sharing**. Shared costs go through the **Common** tab."
  Update memory `family-finance-model.md` (implemented, commit ids).

- [ ] **Step 4: Full check and commit**

```bash
$S/venv/bin/python -m pytest tests -q
$S/venv/bin/black --check backend tests && $S/venv/bin/flake8 backend tests
cd frontend && npm run lint && npm run type-check && npm run build && cd ..
git add tests/smoke_test.py README_DOCKER.md
git commit -m "test: smoke-test the common budget; document sharing"
```
