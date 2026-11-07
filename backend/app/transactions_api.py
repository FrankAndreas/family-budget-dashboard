"""Bookings on an account: list, add, change, delete (the rules are in bookings.py)."""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import attachments, auth, bookings, crud, database, messages, models, privacy, reconcile, schemas
from .seed import SETTLE_UP

router = APIRouter()


@router.get("/accounts/{account_id}/transactions", response_model=List[schemas.Transaction])
def get_transactions(
    account_id: str,
    skip: int = 0,
    limit: int = 100,
    open: bool = False,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Check if user has access to this account (with privacy enforcement)
    privacy.check_account_access(db, current_user, account_id)
    if open:
        # All open points, however old: they are what is left to do
        everything = reconcile.annotate(db, crud.get_transactions(db, account_id=account_id, skip=0, limit=None))
        return [t for t in everything if reconcile.is_open(t.state)]
    return reconcile.annotate(db, crud.get_transactions(db, account_id=account_id, skip=skip, limit=limit))


@router.post("/transactions", response_model=schemas.Transaction)
def create_transaction(
    transaction: schemas.TransactionCreate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return bookings.create(db, current_user, transaction)


@router.put("/transactions/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: str,
    transaction_update: schemas.TransactionUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return reconcile.annotate(db, [bookings.update(db, current_user, transaction_id, transaction_update)])[0]


@router.delete("/transactions/{transaction_id}", response_model=schemas.Transaction)
def delete_transaction(
    transaction_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    db_transaction = crud.get_transaction(db, transaction_id)
    if not db_transaction:
        raise messages.api_error(404, "transaction_not_found")
    # Same access rules as adding transactions on the account
    privacy.check_account_access(db, current_user, db_transaction.account_id, write=True)
    if crud.get_category(db, db_transaction.category_id).system_key == SETTLE_UP:
        raise messages.api_error(400, "undo_settlement_in_common")
    files = [a.id for a in db_transaction.attachments]
    deleted = crud.delete_transaction(db, db_transaction)
    attachments.remove_files(files)
    return deleted
