from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import math
from datetime import timedelta
from fastapi import Body

from . import crud, schemas, auth, database, models, privacy, reports
from .common_api import apply_item_decisions, visible_owner
from .seed import SETTLE_UP

logger = logging.getLogger(__name__)

router = APIRouter()


def is_dependent(user) -> bool:
    """A child without own allowance: no own accounts or budgets; their costs are tagged household expenses."""
    return user.role == "CHILD" and not user.has_allowance


def check_member_tag(db: Session, member_id: Optional[str], account_id: str) -> None:
    """A transaction may only be tagged with a dependent child, and only on a household (parent) account."""
    if member_id is None:
        return
    member = db.query(crud.models.User).filter(crud.models.User.id == member_id).first()
    if not member or not is_dependent(member):
        raise HTTPException(status_code=400, detail="Expenses can only be tagged with a child without own allowance")
    account = crud.get_account(db, account_id)
    owner = db.query(crud.models.User).filter(crud.models.User.id == account.user_id).first()
    if not owner or owner.role != "PARENT":
        raise HTTPException(status_code=400, detail="Only household expenses can be tagged with a child")


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


def check_asset(db: Session, current_user, asset_id: Optional[str]) -> None:
    """An expense can belong to an investment the current user can see."""
    if asset_id is None:
        return
    asset = db.query(models.Asset).filter(models.Asset.id == asset_id).first()
    if not asset or not visible_owner(db, current_user, asset.owner_id, asset.split_id):
        raise HTTPException(status_code=400, detail="Investment not found")


# Auth Routes
@router.post("/users", response_model=schemas.User)
def create_user(
    user: schemas.UserCreate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # No public sign-up: parents add family members (the first parent is created on startup)
    if current_user.role != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can add family members")
    if crud.get_user_by_username(db, username=user.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud.create_user(db=db, user=user)


@router.post("/login", response_model=schemas.Token)
def login(user: schemas.UserLogin, db: Session = Depends(database.get_db)):
    db_user = crud.get_user_by_username(db, username=user.username)
    now = auth.now()
    # Locked after too many wrong PINs: refused even with the right PIN, so guessing can't go on
    if db_user and db_user.locked_until and db_user.locked_until > now:
        minutes = math.ceil((db_user.locked_until - now).total_seconds() / 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many wrong PINs. Try again in {minutes} minute{'' if minutes == 1 else 's'}.",
        )
    if not db_user or not db_user.pin_hash or not auth.verify_pin(user.pin, db_user.pin_hash):
        # Unknown names aren't counted (nothing to protect, and it doesn't reveal which names exist)
        if db_user and db_user.pin_hash:
            db_user.failed_logins = (db_user.failed_logins or 0) + 1
            if db_user.failed_logins >= auth.MAX_WRONG_PINS:
                db_user.locked_until = now + timedelta(minutes=auth.LOCK_MINUTES)
                db_user.failed_logins = 0
                logger.warning(
                    "Login for '%s' locked for %d minutes after %d wrong PINs",
                    db_user.username,
                    auth.LOCK_MINUTES,
                    auth.MAX_WRONG_PINS,
                )
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or PIN",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not db_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been deactivated")
    if db_user.failed_logins or db_user.locked_until:
        db_user.failed_logins, db_user.locked_until = 0, None
        db.commit()
    access_token = auth.create_access_token(
        data={"sub": db_user.id},
        expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users", response_model=List[schemas.User])
def read_users(
    current_user: schemas.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    return [user for user in db.query(crud.models.User).all() if privacy.can_list_user(current_user, user)]


@router.post("/members", response_model=schemas.User)
def create_member(
    member: schemas.MemberCreate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # A parent adds a younger child who has no own money and no login
    if current_user.role != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can add family members")
    if crud.get_user_by_username(db, username=member.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud.create_member(db, username=member.username)


@router.get("/me", response_model=schemas.User)
def read_users_me(current_user: schemas.User = Depends(auth.get_current_user_from_token)):
    return current_user


@router.put("/users/{user_id}", response_model=schemas.User)
def update_user(
    user_id: str,
    user_update: schemas.UserUpdate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Only PARENT can update other users (or themselves)
    # CHILD can update themselves? Maybe just Parents for now based on requirements "Admin user... edit a user"
    if current_user.role != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can update users")

    target_user = db.query(crud.models.User).filter(crud.models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if user_update.username is not None:
        existing = crud.get_user_by_username(db, username=user_update.username)
        if existing and existing.id != target_user.id:
            raise HTTPException(status_code=400, detail="That name is already taken")

    # Deactivating or demoting an active parent must leave at least one other active parent
    is_active_parent = target_user.role == "PARENT" and target_user.is_active
    removes_parent = user_update.is_active is False or (user_update.role is not None and user_update.role != "PARENT")
    if is_active_parent and removes_parent and crud.count_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="Cannot deactivate or demote the last admin user")

    if user_update.has_allowance is not None and user_update.has_allowance != target_user.has_allowance:
        if target_user.role != "CHILD":
            raise HTTPException(status_code=400, detail="Only children can have an own allowance")
        # Getting an own allowance means logging in and managing money, so the child needs a PIN
        if user_update.has_allowance and not target_user.pin_hash and not user_update.pin:
            raise HTTPException(status_code=400, detail="Set a PIN so the child can log in")
        if not user_update.has_allowance and crud.get_accounts(db, user_id):
            raise HTTPException(status_code=400, detail="Delete the child's own accounts first")

    return crud.update_user(db, user_id, user_update)


@router.delete("/users/{user_id}", response_model=schemas.User)
def delete_user(
    user_id: str,
    removal: Optional[schemas.MemberRemoval] = Body(default=None),
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if current_user.role != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can delete users")

    user_to_delete = db.query(crud.models.User).filter(crud.models.User.id == user_id).first()
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if we are deleting an admin (PARENT)
    if user_to_delete.role == "PARENT":
        # Check if it's the last active admin
        admin_count = crud.count_admins(db)
        # If we are deleting/inactivating an active admin, we need to ensure at least one OTHER active admin remains
        # If user is active, count includes them. So if count <= 1, we can't delete.
        if user_to_delete.is_active and admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin user")

    # Their investments and yearly bills go where the parent decided (409 lists any without a decision)
    apply_item_decisions(db, user_id, removal.items if removal else [])
    return crud.delete_user(db, user_id)


@router.patch("/me/privacy")
def update_privacy(
    privacy_update: dict,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Only children can update their own privacy settings
    if current_user.role != "CHILD":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only child accounts can modify privacy settings"
        )

    db_user = db.query(crud.models.User).filter(crud.models.User.id == current_user.id).first()
    if db_user:
        db_user.privacy_enabled = privacy_update.get("privacy_enabled", db_user.privacy_enabled)
        db.commit()
        db.refresh(db_user)

    return {"message": "Privacy settings updated", "privacy_enabled": db_user.privacy_enabled}


# Account Routes
@router.get("/accounts", response_model=List[schemas.Account])
def get_accounts(
    current_user: schemas.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    # Return all accounts the user has access to (own, the other parents', children without privacy)
    return privacy.get_accessible_accounts(db, current_user)


@router.post("/accounts", response_model=schemas.Account)
def create_account(
    account: schemas.AccountCreate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if is_dependent(current_user):
        raise HTTPException(status_code=403, detail="Children without own allowance can't have accounts")
    owner = (
        privacy.check_user_access(db, current_user, account.user_id, write=True) if account.user_id else current_user
    )
    if is_dependent(owner):
        raise HTTPException(status_code=403, detail="Children without own allowance can't have accounts")
    return crud.create_account(db, account=account, user_id=owner.id)


def get_own_account(db: Session, current_user, account_id: str):
    # The owner, or someone they shared their finances with as EDIT
    return privacy.check_account_access(db, current_user, account_id, write=True)


@router.put("/accounts/{account_id}", response_model=schemas.Account)
def update_account(
    account_id: str,
    account_update: schemas.AccountUpdate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return crud.update_account(db, get_own_account(db, current_user, account_id), account_update)


@router.delete("/accounts/{account_id}", response_model=schemas.Account)
def delete_account(
    account_id: str,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Deleting an account also deletes all its transactions
    return crud.delete_account(db, get_own_account(db, current_user, account_id))


# Category Routes
@router.get("/categories", response_model=List[schemas.Category])
def get_categories(db: Session = Depends(database.get_db)):
    return crud.get_categories(db)


@router.post("/categories", response_model=schemas.Category)
def create_category(
    category: schemas.CategoryCreate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Only parents can create categories
    if current_user.role != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can create categories")
    return crud.create_category(db, category=category)


# Transaction Routes
@router.get("/accounts/{account_id}/transactions", response_model=List[schemas.Transaction])
def get_transactions(
    account_id: str,
    skip: int = 0,
    limit: int = 100,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Check if user has access to this account (with privacy enforcement)
    privacy.check_account_access(db, current_user, account_id)
    return crud.get_transactions(db, account_id=account_id, skip=skip, limit=limit)


@router.post("/transactions", response_model=schemas.Transaction)
def create_transaction(
    transaction: schemas.TransactionCreate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Check if user has access to this account (with privacy enforcement)
    privacy.check_account_access(db, current_user, transaction.account_id, write=True)
    category = crud.get_category(db, transaction.category_id)
    if not category:
        raise HTTPException(status_code=400, detail="Category not found")
    if category.type == models.CategoryType.TRANSFER:
        raise HTTPException(status_code=400, detail="Transfers are booked with Settle up")
    check_member_tag(db, transaction.member_id, transaction.account_id)
    split_shares = check_shared(db, transaction.split_id, transaction.account_id, category)
    check_asset(db, current_user, transaction.asset_id)
    return crud.create_transaction(db, transaction=transaction, category=category, split_shares=split_shares)


@router.put("/transactions/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: str,
    transaction_update: schemas.TransactionUpdate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    db_transaction = crud.get_transaction(db, transaction_id)
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    privacy.check_account_access(db, current_user, db_transaction.account_id, write=True)

    current = crud.get_category(db, db_transaction.category_id)
    if current.type == models.CategoryType.TRANSFER:
        return update_transfer(db, db_transaction, transaction_update, current)
    category = crud.get_category(db, transaction_update.category_id or db_transaction.category_id)
    if not category:
        raise HTTPException(status_code=400, detail="Category not found")
    if category.type == models.CategoryType.TRANSFER:
        raise HTTPException(status_code=400, detail="Transfers are booked with Settle up")
    check_member_tag(db, transaction_update.member_id, db_transaction.account_id)
    # The split's percents are read again only when the split itself changes; otherwise the
    # booked copy stays (also when that split was deleted since)
    fields = transaction_update.model_fields_set
    if "asset_id" in fields:
        check_asset(db, current_user, transaction_update.asset_id)
    if "split_id" in fields and transaction_update.split_id != db_transaction.split_id:
        split_shares = check_shared(db, transaction_update.split_id, db_transaction.account_id, category)
    else:
        split_shares = db_transaction.split_shares
        if db_transaction.split_shares and category.type != models.CategoryType.EXPENSE:
            raise HTTPException(status_code=400, detail="Only expenses can be shared")
    return crud.update_transaction(db, db_transaction, transaction_update, category, split_shares=split_shares)


def update_transfer(db: Session, db_transaction, update: schemas.TransactionUpdate, category: models.Category):
    """An imported transfer keeps its amount and category (delete and import again); Settle up stays as booked."""
    if category.name == SETTLE_UP:
        raise HTTPException(status_code=400, detail="Undo the settlement in the Common tab instead")
    changed = update.model_fields_set - {"description", "date"}
    if update.category_id == db_transaction.category_id:
        changed.discard("category_id")
    if changed:
        raise HTTPException(status_code=400, detail="Only the date and description of a transfer can be changed")
    return crud.update_transaction(db, db_transaction, update, category)


@router.delete("/transactions/{transaction_id}", response_model=schemas.Transaction)
def delete_transaction(
    transaction_id: str,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    db_transaction = crud.get_transaction(db, transaction_id)
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Same access rules as adding transactions on the account
    privacy.check_account_access(db, current_user, db_transaction.account_id, write=True)
    if crud.get_category(db, db_transaction.category_id).name == SETTLE_UP:
        raise HTTPException(status_code=400, detail="Undo the settlement in the Common tab instead")
    return crud.delete_transaction(db, db_transaction)


# Budget Routes
@router.get("/budgets", response_model=List[schemas.Budget])
def get_budgets(
    user_id: Optional[str] = None,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Without user_id: the caller's own budgets. With user_id: someone else's they may view.
    owner = privacy.check_user_access(db, current_user, user_id) if user_id else current_user
    return [reports.budget_out(db, budget) for budget in crud.get_budgets(db, owner.id)]


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
    return reports.budget_out(db, crud.create_budget(db, budget=budget, user_id=owner.id))


def get_manageable_budget(db: Session, current_user, budget_id: str):
    db_budget = crud.get_budget(db, budget_id)
    owner = db.query(models.User).filter(models.User.id == db_budget.user_id).first() if db_budget else None
    # Own budgets, or those of someone who shared with EDIT
    if not owner or not privacy.can_write(privacy.access_level(db, current_user, owner)):
        raise HTTPException(status_code=404, detail="Budget not found")
    return db_budget


@router.put("/budgets/{budget_id}", response_model=schemas.Budget)
def update_budget(
    budget_id: str,
    budget_update: schemas.BudgetUpdate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return reports.budget_out(
        db, crud.update_budget(db, get_manageable_budget(db, current_user, budget_id), budget_update)
    )


@router.delete("/budgets/{budget_id}", response_model=schemas.Budget)
def delete_budget(
    budget_id: str,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return crud.delete_budget(db, get_manageable_budget(db, current_user, budget_id))


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
    if is_dependent(current_user):
        raise HTTPException(status_code=403, detail="Children without own allowance have nothing to share")
    grantee = db.query(models.User).filter(models.User.id == grantee_id).first()
    if not grantee or grantee.role != "PARENT" or grantee.id == current_user.id:
        raise HTTPException(status_code=400, detail="You can only share with a parent")
    crud.set_share(db, current_user, grantee_id, share.level)
    return {"level": share.level}
