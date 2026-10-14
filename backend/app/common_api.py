"""Common budget, splits, settlements, planned costs (yearly bills) and assets (investments). Parents only."""

from datetime import datetime
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
