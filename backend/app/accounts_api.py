"""Accounts: a person's bank accounts, cash and clearing accounts."""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, crud, database, messages, models, privacy, reconcile, schemas
from .privacy import is_dependent

router = APIRouter()


@router.get("/accounts", response_model=List[schemas.Account])
def get_accounts(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    # Return all accounts the user has access to (own, the other parents', children without privacy)
    accounts = privacy.get_accessible_accounts(db, current_user)
    for account in accounts:
        for name, value in reconcile.summary(db, account).items():
            setattr(account, name, value)
    return accounts


@router.post("/accounts", response_model=schemas.Account)
def create_account(
    account: schemas.AccountCreate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if is_dependent(current_user):
        raise messages.api_error(403, "no_accounts_without_allowance")
    owner = (
        privacy.check_user_access(db, current_user, account.user_id, write=True) if account.user_id else current_user
    )
    if is_dependent(owner):
        raise messages.api_error(403, "no_accounts_without_allowance")
    if account.iban and current_user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_set_iban")
    return crud.create_account(db, account=account, user_id=owner.id)


def get_own_account(db: Session, current_user, account_id: str):
    # The owner, or someone they shared their finances with as EDIT
    return privacy.check_account_access(db, current_user, account_id, write=True)


@router.put("/accounts/{account_id}", response_model=schemas.Account)
def update_account(
    account_id: str,
    account_update: schemas.AccountUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if "iban" in account_update.model_fields_set and current_user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_set_iban")
    return crud.update_account(db, get_own_account(db, current_user, account_id), account_update)


@router.delete("/accounts/{account_id}", response_model=schemas.Account)
def delete_account(
    account_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Deleting an account also deletes all its transactions
    return crud.delete_account(db, get_own_account(db, current_user, account_id))
