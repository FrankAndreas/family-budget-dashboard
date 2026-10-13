from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import timedelta
from . import crud, schemas, auth, database, models, privacy

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
    if not db_user or not db_user.pin_hash or not auth.verify_pin(user.pin, db_user.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or PIN",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not db_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been deactivated")
    access_token = auth.create_access_token(
        data={"sub": db_user.id},
        expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users", response_model=List[schemas.User])
def read_users(
    current_user: schemas.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    # Get all users and filter by privacy settings
    all_users = db.query(crud.models.User).all()
    accessible_users = privacy.filter_users_by_privacy(all_users, current_user)
    return accessible_users


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
    return crud.create_account(db, account=account, user_id=current_user.id)


def get_own_account(db: Session, current_user, account_id: str):
    account = privacy.check_account_access(db, current_user, account_id)
    # Only the owner can change or delete an account
    if account.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the account owner can change it")
    return account


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
    privacy.check_account_access(db, current_user, transaction.account_id)
    category = crud.get_category(db, transaction.category_id)
    if not category:
        raise HTTPException(status_code=400, detail="Category not found")
    check_member_tag(db, transaction.member_id, transaction.account_id)
    return crud.create_transaction(db, transaction=transaction, category=category)


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
    privacy.check_account_access(db, current_user, db_transaction.account_id)

    category = crud.get_category(db, transaction_update.category_id or db_transaction.category_id)
    if not category:
        raise HTTPException(status_code=400, detail="Category not found")
    check_member_tag(db, transaction_update.member_id, db_transaction.account_id)
    return crud.update_transaction(db, db_transaction, transaction_update, category)


@router.delete("/transactions/{transaction_id}", response_model=schemas.Transaction)
def delete_transaction(
    transaction_id: str,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    db_transaction = crud.get_transaction(db, transaction_id)
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Same access rules as viewing or adding transactions on the account
    privacy.check_account_access(db, current_user, db_transaction.account_id)
    return crud.delete_transaction(db, db_transaction)


# Budget Routes
def budget_owner_ids(db: Session, owner) -> list[str]:
    # Parents share household budgets; a child with own allowance has their own
    if owner.role == "PARENT":
        return privacy.get_household_user_ids(db)
    return [owner.id]


@router.get("/budgets", response_model=List[schemas.Budget])
def get_budgets(
    user_id: Optional[str] = None,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Without user_id: the caller's own scope (household for parents). With user_id: inspect that user's budgets.
    owner = privacy.check_user_access(db, current_user, user_id) if user_id else current_user
    return crud.get_budgets_for_users(db, budget_owner_ids(db, owner))


@router.post("/budgets", response_model=schemas.Budget)
def create_budget(
    budget: schemas.BudgetCreate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if is_dependent(current_user):
        raise HTTPException(status_code=403, detail="Children without own allowance can't have budgets")
    if not crud.get_category(db, budget.category_id):
        raise HTTPException(status_code=400, detail="Category not found")
    return crud.create_budget(db, budget=budget, user_id=current_user.id)


def get_manageable_budget(db: Session, current_user, budget_id: str):
    db_budget = crud.get_budget(db, budget_id)
    # Own budgets, or any household budget for a parent
    if not db_budget or db_budget.user_id not in budget_owner_ids(db, current_user):
        raise HTTPException(status_code=404, detail="Budget not found")
    return db_budget


@router.put("/budgets/{budget_id}", response_model=schemas.Budget)
def update_budget(
    budget_id: str,
    budget_update: schemas.BudgetUpdate,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return crud.update_budget(db, get_manageable_budget(db, current_user, budget_id), budget_update)


@router.delete("/budgets/{budget_id}", response_model=schemas.Budget)
def delete_budget(
    budget_id: str,
    current_user: schemas.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return crud.delete_budget(db, get_manageable_budget(db, current_user, budget_id))
