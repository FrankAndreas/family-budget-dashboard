from sqlalchemy.orm import Session
from . import models, schemas, auth
from datetime import datetime, timezone


# User CRUD
def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def create_user(db: Session, user: schemas.UserCreate):
    hashed_pin = auth.get_pin_hash(user.pin)
    db_user = models.User(
        username=user.username,
        pin_hash=hashed_pin,
        role=user.role,
        # A child with a login manages own money; younger children are added via create_member
        has_allowance=True,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def create_member(db: Session, username: str):
    db_user = models.User(username=username, pin_hash=None, role=models.UserRole.CHILD, has_allowance=False)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(db: Session, user_id: str, user_update: schemas.UserUpdate):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        return None

    update_data = user_update.dict(exclude_unset=True)

    # Handle PIN update separately to hash it
    if "pin" in update_data:
        update_data["pin_hash"] = auth.get_pin_hash(update_data.pop("pin"))

    for key, value in update_data.items():
        setattr(db_user, key, value)

    db.commit()
    db.refresh(db_user)
    return db_user


def count_admins(db: Session):
    return (
        db.query(models.User)
        .filter(models.User.role == models.UserRole.PARENT, models.User.is_active.is_(True))
        .count()
    )


def delete_user(db: Session, user_id: str):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        return None

    # SQLite doesn't enforce foreign keys here, so remove the user's data explicitly
    account_ids = [a.id for a in db.query(models.Account.id).filter(models.Account.user_id == user_id)]
    if account_ids:
        db.query(models.Transaction).filter(models.Transaction.account_id.in_(account_ids)).delete(
            synchronize_session=False
        )
    db.query(models.Account).filter(models.Account.user_id == user_id).delete(synchronize_session=False)
    db.query(models.Budget).filter(models.Budget.user_id == user_id).delete(synchronize_session=False)
    # Expenses tagged with this child stay; only the tag goes
    db.query(models.Transaction).filter(models.Transaction.member_id == user_id).update(
        {models.Transaction.member_id: None}, synchronize_session=False
    )

    db.query(models.Share).filter((models.Share.owner_id == user_id) | (models.Share.grantee_id == user_id)).delete(
        synchronize_session=False
    )

    db.delete(db_user)
    db.commit()
    return db_user


def set_share(db: Session, owner: models.User, grantee_id: str, level: str):
    db.query(models.Share).filter(models.Share.owner_id == owner.id, models.Share.grantee_id == grantee_id).delete(
        synchronize_session=False
    )
    # No row means "none" for a parent's finances but "view" for a child's, so a child's NONE is stored
    if level != "NONE" or owner.role == models.UserRole.CHILD:
        db.add(models.Share(owner_id=owner.id, grantee_id=grantee_id, level=level))
    db.commit()


# Account CRUD
def get_accounts(db: Session, user_id: str):
    return db.query(models.Account).filter(models.Account.user_id == user_id).all()


def create_account(db: Session, account: schemas.AccountCreate, user_id: str):
    db_account = models.Account(user_id=user_id, name=account.name, type=account.type, balance=0.0)
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account


def get_account(db: Session, account_id: str):
    return db.query(models.Account).filter(models.Account.id == account_id).first()


def update_account(db: Session, db_account: models.Account, update: schemas.AccountUpdate):
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(db_account, key, value)
    db.commit()
    db.refresh(db_account)
    return db_account


def delete_account(db: Session, db_account: models.Account):
    db.query(models.Transaction).filter(models.Transaction.account_id == db_account.id).delete(
        synchronize_session=False
    )
    db.delete(db_account)
    db.commit()
    return db_account


# Category CRUD
def get_categories(db: Session):
    return db.query(models.Category).all()


def create_category(db: Session, category: schemas.CategoryCreate):
    db_category = models.Category(name=category.name, type=category.type, icon=category.icon, is_global=True)
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


# Transaction CRUD
def get_transactions(db: Session, account_id: str, skip: int = 0, limit: int = 100):
    return (
        db.query(models.Transaction)
        .filter(models.Transaction.account_id == account_id)
        .order_by(models.Transaction.date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def to_cents(value: float) -> float:
    # Money is stored as float; rounding every stored value keeps sums from drifting
    return round(value, 2)


def to_naive_utc(value: datetime) -> datetime:
    # Stored dates are naive UTC; naive input is assumed to already be UTC
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_category(db: Session, category_id: str):
    return db.query(models.Category).filter(models.Category.id == category_id).first()


def signed_amount(amount: float, category: models.Category) -> float:
    # The category decides the sign: income is positive, expenses are negative; transfers keep their sign
    if category.type == models.CategoryType.TRANSFER:
        return to_cents(amount)
    if category.type == models.CategoryType.INCOME:
        return to_cents(abs(amount))
    return to_cents(-abs(amount))


def create_transaction(db: Session, transaction: schemas.TransactionCreate, category: models.Category):
    amount = signed_amount(transaction.amount, category)
    db_transaction = models.Transaction(
        account_id=transaction.account_id,
        category_id=transaction.category_id,
        amount=amount,
        description=transaction.description,
        member_id=transaction.member_id,
        date=to_naive_utc(transaction.date) if transaction.date else datetime.utcnow(),
    )
    db.add(db_transaction)

    # Update account balance
    account = get_account(db, transaction.account_id)
    if account:
        account.balance = to_cents(account.balance + amount)

    db.commit()
    db.refresh(db_transaction)
    return db_transaction


def update_transaction(
    db: Session, db_transaction: models.Transaction, update: schemas.TransactionUpdate, category: models.Category
):
    old_amount = db_transaction.amount
    update_data = update.model_dump(exclude_unset=True)

    if update_data.get("date"):
        update_data["date"] = to_naive_utc(update_data["date"])
    # Re-derive the sign: either the amount or the category may have changed
    update_data["amount"] = signed_amount(update_data.get("amount", old_amount), category)

    for key, value in update_data.items():
        setattr(db_transaction, key, value)

    account = get_account(db, db_transaction.account_id)
    if account:
        account.balance = to_cents(account.balance + db_transaction.amount - old_amount)

    db.commit()
    db.refresh(db_transaction)
    return db_transaction


def get_transaction(db: Session, transaction_id: str):
    return db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()


def delete_transaction(db: Session, db_transaction: models.Transaction):
    # Undo the transaction's effect on the account balance
    account = get_account(db, db_transaction.account_id)
    if account:
        account.balance = to_cents(account.balance - db_transaction.amount)

    db.delete(db_transaction)
    db.commit()
    return db_transaction


# Budget CRUD
def get_budgets(db: Session, user_id: str):
    return db.query(models.Budget).filter(models.Budget.user_id == user_id).all()


def create_budget(db: Session, budget: schemas.BudgetCreate, user_id: str):
    db_budget = models.Budget(
        user_id=user_id, category_id=budget.category_id, limit=to_cents(budget.limit), period=budget.period
    )
    db.add(db_budget)
    db.commit()
    db.refresh(db_budget)
    return db_budget


def get_budget(db: Session, budget_id: str):
    return db.query(models.Budget).filter(models.Budget.id == budget_id).first()


def update_budget(db: Session, db_budget: models.Budget, update: schemas.BudgetUpdate):
    update_data = update.model_dump(exclude_unset=True)
    if "limit" in update_data:
        update_data["limit"] = to_cents(update_data["limit"])
    for key, value in update_data.items():
        setattr(db_budget, key, value)
    db.commit()
    db.refresh(db_budget)
    return db_budget


def delete_budget(db: Session, db_budget: models.Budget):
    db.delete(db_budget)
    db.commit()
    return db_budget
