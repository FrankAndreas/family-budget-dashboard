"""Splits (how the parents share common costs), the common balance and settling up. Parents only."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from . import auth, common_budget, crud, database, finance, messages, models, ownership, privacy, schemas
from .money import cents
from .seed import SETTLE_UP, system_category

router = APIRouter()


MAX_SPLITS = 4


def validate_split(db: Session, split: schemas.SplitIn, split_id: Optional[str] = None) -> None:
    parent_ids = {p.id for p in privacy.active_parents(db)}
    if set(split.shares) != parent_ids:
        raise messages.api_error(400, "split_every_parent")
    if sum(split.shares.values()) != 100:
        raise messages.api_error(400, "split_sum_100")
    same_name = db.query(models.Split).filter(models.Split.name == split.name, models.Split.id != split_id).first()
    if same_name:
        raise messages.api_error(400, "split_name_taken")


@router.get("/splits", response_model=List[schemas.Split])
def list_splits(_: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)):
    return db.query(models.Split).order_by(models.Split.name).all()


@router.post("/splits", response_model=schemas.Split)
def create_split(
    split: schemas.SplitIn, _: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)
):
    if db.query(models.Split).count() >= MAX_SPLITS:
        raise messages.api_error(400, "max_splits", count=MAX_SPLITS)
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
    _: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    db_split = ownership.get_split(db, split_id)
    validate_split(db, split, split_id)
    db_split.name, db_split.shares = split.name, split.shares
    db.commit()
    db.refresh(db_split)
    return db_split


@router.delete("/splits/{split_id}", response_model=schemas.Split)
def delete_split(split_id: str, _: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)):
    db_split = ownership.get_split(db, split_id)
    in_use = any(
        db.query(model).filter(model.split_id == split_id).first()
        for model in (models.PlannedCost, models.Asset, models.Wish)
    )
    if in_use:
        raise messages.api_error(409, "split_in_use")
    # Shared expenses keep the percentages they were booked with (split_shares); only the link goes
    db.query(models.Transaction).filter(models.Transaction.split_id == split_id).update(
        {models.Transaction.split_id: None}, synchronize_session=False
    )
    db.delete(db_split)
    db.commit()
    return db_split


@router.get("/common/balance", response_model=List[schemas.Balance])
def common_balance(_: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)):
    net = finance.balances(common_budget.shared_expense_rows(db), common_budget.settlement_rows(db))
    for parent in privacy.active_parents(db):
        net.setdefault(parent.id, 0.0)
    return [{"user_id": user_id, "amount": amount} for user_id, amount in net.items()]


@router.get("/common/expenses", response_model=List[schemas.SharedExpense])
def common_expenses(
    limit: Optional[int] = Query(default=None, ge=1),
    _: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    """The shared expenses, newest first; the Common tab asks only for the newest (performance review 2026-11-08)."""
    split_names = {s.id: s.name for s in db.query(models.Split)}
    return [
        {
            "transaction_id": t.id,
            "date": t.date,
            "description": t.description,
            "amount": crud.cost(t.amount),
            "payer_id": payer,
            "split_name": split_names.get(t.split_id or ""),
            "shares": finance.split_amount(crud.cost(t.amount), t.split_shares or {}),
        }
        for t, payer in common_budget.shared_transactions(db, limit)
    ]


def parent_account(db: Session, account_id: str, user_id: str) -> models.Account:
    account = crud.get_account(db, account_id)
    if not account or account.user_id != user_id:
        raise messages.api_error(400, "settle_pick_accounts")
    return account


@router.get("/settlements", response_model=List[schemas.Settlement])
def list_settlements(_: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)):
    return db.query(models.Settlement).order_by(models.Settlement.date.desc()).all()


@router.post("/settlements", response_model=schemas.Settlement)
def create_settlement(
    settlement: schemas.SettlementCreate,
    _: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    # Also a deactivated parent, whose open balance must still be settled
    parent_ids = {p.id for p in db.query(models.User.id).filter(models.User.role == models.UserRole.PARENT)}
    between = {settlement.from_user_id, settlement.to_user_id}
    if settlement.from_user_id == settlement.to_user_id or not between <= parent_ids:
        raise messages.api_error(400, "settle_two_parents")
    from_account = parent_account(db, settlement.from_account_id, settlement.from_user_id)
    to_account = parent_account(db, settlement.to_account_id, settlement.to_user_id)
    category = system_category(db, SETTLE_UP)
    amount = cents(settlement.amount)
    when = crud.to_naive_utc(settlement.date) if settlement.date else datetime.utcnow()

    paid, received = (
        models.Transaction(
            account_id=account.id,
            category_id=category.id,
            amount=sign * amount,
            date=when,
            description=messages.text("settle_up_description"),
        )
        for account, sign in ((from_account, -1), (to_account, 1))
    )
    db.add_all([paid, received])
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
    settlement_id: str, _: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)
):
    db_settlement = db.query(models.Settlement).filter(models.Settlement.id == settlement_id).first()
    if not db_settlement:
        raise messages.api_error(404, "settlement_not_found")
    transaction_ids = (db_settlement.from_transaction_id, db_settlement.to_transaction_id)
    # The record points to its two transactions, so it goes first
    db.delete(db_settlement)
    db.flush()
    for transaction_id in transaction_ids:
        transaction = crud.get_transaction(db, transaction_id)
        if transaction:
            crud.delete_transaction(db, transaction)
    db.commit()
    return db_settlement
