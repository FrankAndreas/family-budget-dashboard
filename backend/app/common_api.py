"""Common budget, splits, settlements, planned costs (yearly bills) and assets (investments). Parents only."""

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import auth, crud, database, finance, models, privacy, schemas
from .seed import SETTLE_UP

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


def validate_split(db: Session, split: schemas.SplitIn, split_id: Optional[str] = None) -> None:
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
def create_split(
    split: schemas.SplitIn, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
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
    split_id: str,
    split: schemas.SplitIn,
    _: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
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
    if db.query(models.PlannedCost).filter(models.PlannedCost.split_id == split_id).first():
        raise HTTPException(status_code=409, detail="In use by a planned cost; change or delete it first")
    db.delete(db_split)
    db.commit()
    return db_split


def shared_transactions(db: Session) -> list[tuple[models.Transaction, str]]:
    """Every shared expense with its payer's user id, newest first."""
    rows = (
        db.query(models.Transaction, models.Account.user_id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .filter(models.Transaction.split_id.isnot(None))
        .order_by(models.Transaction.date.desc())
        .all()
    )
    return [(transaction, payer) for transaction, payer in rows]


def shared_expense_rows(db: Session) -> list[tuple[str, float, dict[str, int]]]:
    return [(payer, abs(t.amount), t.split_shares or {}) for t, payer in shared_transactions(db)]


def settlement_rows(db: Session) -> list[tuple[str, str, float]]:
    return [(s.from_user_id, s.to_user_id, s.amount) for s in db.query(models.Settlement)]


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
    between = {settlement.from_user_id, settlement.to_user_id}
    if settlement.from_user_id == settlement.to_user_id or not between <= parent_ids:
        raise HTTPException(status_code=400, detail="Settling up is between two parents")
    from_account = parent_account(db, settlement.from_account_id, settlement.from_user_id)
    to_account = parent_account(db, settlement.to_account_id, settlement.to_user_id)
    category = db.query(models.Category).filter(models.Category.name == SETTLE_UP).one()
    amount = crud.to_cents(settlement.amount)
    when = crud.to_naive_utc(settlement.date) if settlement.date else datetime.utcnow()

    paid, received = (
        models.Transaction(
            account_id=account.id, category_id=category.id, amount=sign * amount, date=when, description="Settle up"
        )
        for account, sign in ((from_account, -1), (to_account, 1))
    )
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
def delete_settlement(
    settlement_id: str, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
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


def today() -> date:
    return date.today()


def visible_owner(
    db: Session, current_user: models.User, owner_id: Optional[str], split_id: Optional[str], write: bool = False
) -> bool:
    """Common items belong to all parents; a personal item follows the access rules for its owner's money."""
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
        raise HTTPException(status_code=403, detail="You can't manage that person's items")


def monthly_shares(db: Session, monthly: float, owner_id: Optional[str], split_id: Optional[str]) -> dict[str, float]:
    if split_id:
        split = db.query(models.Split).filter(models.Split.id == split_id).first()
        return finance.split_amount(monthly, split.shares if split else {})
    return {owner_id: monthly} if owner_id else {}


PLANNED_COST_FIELDS = ("id", "name", "category_id", "amount", "due_month", "owner_id", "split_id", "notes")


def planned_cost_out(db: Session, cost: models.PlannedCost) -> dict:
    monthly = finance.monthly_equivalent(cost.amount, cost.frequency.value)
    due = finance.next_due(cost.due_month, today()) if cost.due_month else None
    return {
        **{field: getattr(cost, field) for field in PLANNED_COST_FIELDS},
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
    rows = [planned_cost_out(db, c) for c in query if visible_owner(db, current_user, c.owner_id, c.split_id)]
    return sorted(rows, key=lambda r: (r["next_due"] or date.max, r["name"]))


@router.post("/planned-costs", response_model=schemas.PlannedCost)
def create_planned_cost(
    cost: schemas.PlannedCostIn,
    current_user: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
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
def delete_planned_cost(
    cost_id: str, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    db.delete(get_planned_cost(db, current_user, cost_id, write=True))
    db.commit()
    return {"deleted": cost_id}


def common_asset_items(db: Session) -> list[dict]:
    # Common investments are added in the next task
    return []


@router.get("/common/overview", response_model=schemas.Overview)
def common_overview(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    items = []
    for cost in db.query(models.PlannedCost).filter(models.PlannedCost.split_id.isnot(None)):
        monthly = finance.monthly_equivalent(cost.amount, cost.frequency.value)
        shares = monthly_shares(db, monthly, None, cost.split_id)
        items.append({"kind": "planned", "id": cost.id, "name": cost.name, "monthly": monthly, "shares": shares})
    items += common_asset_items(db)
    totals: dict[str, float] = {}
    for item in items:
        for user_id, amount in item["shares"].items():
            totals[user_id] = finance.cents(totals.get(user_id, 0.0) + amount)
    return {"items": items, "totals": totals}
