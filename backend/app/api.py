from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import os
from datetime import datetime
from fastapi import Body

from . import (
    article_rules,
    attachments,
    crud,
    schemas,
    auth,
    hub,
    hub_people,
    database,
    models,
    privacy,
    reconcile,
    reports,
    items,
    messages,
)
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
        raise messages.api_error(400, "tag_child_without_allowance")
    account = crud.get_account(db, account_id)
    owner = account.user if account else None
    if not owner or owner.role != "PARENT":
        raise messages.api_error(400, "tag_household_only")


def check_shared(db: Session, split_id: Optional[str], account_id: str, category) -> Optional[dict]:
    """A shared expense: an expense on a parent's account with an existing split. Returns the percents to keep."""
    if split_id is None:
        return None
    if category.type != models.CategoryType.EXPENSE:
        raise messages.api_error(400, "share_expenses_only")
    account = crud.get_account(db, account_id)
    owner = account.user if account else None
    if not owner or owner.role != "PARENT":
        raise messages.api_error(400, "share_parent_only")
    split = db.query(models.Split).filter(models.Split.id == split_id).first()
    if not split:
        raise messages.api_error(400, "split_not_found")
    return dict(split.shares)


def check_asset(db: Session, current_user, asset_id: Optional[str], linked: Optional[str] = None) -> None:
    """An expense can belong to an investment the current user can see; to an archived one only if it already did."""
    if asset_id is None:
        return
    asset = db.query(models.Asset).filter(models.Asset.id == asset_id).first()
    if not asset or not visible_owner(db, current_user, asset.owner_id, asset.split_id):
        raise messages.api_error(400, "investment_not_found")
    if asset.archived_on and asset_id != linked:
        raise messages.api_error(400, "investment_archived")


@router.get("/users", response_model=List[schemas.User])
def read_users(
    request: Request,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # The people the family hub lists for this app; removed ones stay hidden with their data (spec 2026-10-30). A
    # parent looking at the family (Settings) sees the hub's list as it is now, not up to a minute old
    if current_user.role == "PARENT":
        token, _ = auth.request_token(request)
        try:
            hub_people.refresh(db, token or "", force=True)
        except hub.HubUnavailable:
            raise messages.CodedError(503, "hub_unavailable") from None
    people = db.query(crud.models.User).filter(crud.models.User.is_active.is_(True)).all()
    return [user for user in people if privacy.can_list_user(current_user, user)]


@router.get("/me", response_model=schemas.User)
def read_users_me(current_user: models.User = Depends(auth.get_current_user_from_token)):
    return current_user


@router.put("/users/{user_id}", response_model=schemas.User)
def update_user(
    user_id: str,
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    """What only this app knows about a person: Jugendlohn and privacy. Name, role and PIN are the family hub's."""
    if current_user.role != "PARENT":
        raise messages.api_error(403, "only_parents_update_users")

    target_user = db.query(crud.models.User).filter(crud.models.User.id == user_id).first()
    if not target_user:
        raise messages.api_error(404, "user_not_found")

    if user_update.has_allowance is not None and user_update.has_allowance != target_user.has_allowance:
        if target_user.role != "CHILD":
            raise messages.api_error(400, "allowance_children_only")
        if not user_update.has_allowance and crud.get_accounts(db, user_id):
            raise messages.api_error(400, "delete_child_accounts_first")

    return crud.update_user(db, user_id, user_update)


@router.post("/logout")
def logout(response: Response):
    """Ends the family login in this browser, for every app: the hub's cookie is set for local.<domain>, which this app
    may clear too. "Log out everywhere" is in the hub."""
    response.delete_cookie(auth.COOKIE, path="/", domain=os.getenv("COOKIE_DOMAIN") or None)
    hub.forget()
    return {"logged_out": True}


@router.get("/hub")
def hub_login():
    """Where the browser logs in (the family hub), for a visitor without a login."""
    return {"login_url": hub.public_url()}


@router.get("/users/removed", response_model=List[schemas.RemovedUser])
def removed_users(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    """People the family hub no longer lists for this app: their data is kept until a parent deletes it here."""
    if current_user.role != "PARENT":
        raise messages.api_error(403, "only_parents_delete_users")
    return (
        db.query(crud.models.User)
        .filter(crud.models.User.is_active.is_(False))
        .order_by(crud.models.User.username)
        .all()
    )


@router.delete("/users/{user_id}", response_model=schemas.User)
def delete_user(
    user_id: str,
    removal: Optional[schemas.MemberRemoval] = Body(default=None),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if current_user.role != "PARENT":
        raise messages.api_error(403, "only_parents_delete_users")

    user_to_delete = db.query(crud.models.User).filter(crud.models.User.id == user_id).first()
    if not user_to_delete:
        raise messages.api_error(404, "user_not_found")
    # Only people the family hub no longer lists: an active family member's data is never deleted by mistake
    if user_to_delete.is_active:
        raise messages.api_error(409, "still_in_hub")

    # Their investments and yearly bills go where the parent decided (409 lists any without a decision)
    apply_item_decisions(db, user_id, removal.items if removal else [])
    return crud.delete_user(db, user_id)


@router.patch("/me/privacy")
def update_privacy(
    privacy_update: dict,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Only children can update their own privacy settings
    if current_user.role != "CHILD":
        raise messages.api_error(status.HTTP_403_FORBIDDEN, "privacy_children_only")

    current_user.privacy_enabled = privacy_update.get("privacy_enabled", current_user.privacy_enabled)
    db.commit()
    db.refresh(current_user)
    return {"message": "Privacy settings updated", "privacy_enabled": current_user.privacy_enabled}


# Account Routes
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


# Transaction Routes
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
    # Check if user has access to this account (with privacy enforcement)
    privacy.check_account_access(db, current_user, transaction.account_id, write=True)
    if transaction.items is not None:
        receipt = create_receipt(db, current_user, transaction)
        return mark_purchase(db, current_user, receipt, transaction.asset_purchase or None)
    # Without items the schema requires both (TransactionCreate.plain_needs_amount_and_category)
    assert transaction.category_id is not None and transaction.amount is not None
    category = crud.get_category(db, transaction.category_id)
    if not category:
        raise messages.api_error(400, "category_not_found")
    if category.type == models.CategoryType.TRANSFER:
        raise messages.api_error(400, "transfers_via_settle_up")
    check_member_tag(db, transaction.member_id, transaction.account_id)
    split_shares = check_shared(db, transaction.split_id, transaction.account_id, category)
    check_asset(db, current_user, transaction.asset_id)
    created = crud.create_transaction(db, transaction=transaction, category=category, split_shares=split_shares)
    created = with_attachments(db, current_user, created, transaction.attachment_ids)
    return mark_purchase(db, current_user, created, transaction.asset_purchase or None)


def mark_purchase(
    db: Session,
    user: models.User,
    transaction: models.Transaction,
    wanted: Optional[bool],
    before: Optional[str] = None,
) -> models.Transaction:
    """Mark (wanted True) or unmark the booking as the one that bought its investment; marking fills the investment's
    price and date. A booking linked to another investment, or to none, is no purchase any more (unless marked)."""
    if wanted:
        if not transaction.asset_id:
            raise messages.api_error(400, "purchase_needs_investment")
        asset = db.query(models.Asset).filter(models.Asset.id == transaction.asset_id).one()
        if not visible_owner(db, user, asset.owner_id, asset.split_id, write=True):
            raise messages.api_error(403, "cant_manage_items")
        if not transaction.asset_purchase:
            db.query(models.Transaction).filter(
                models.Transaction.asset_id == asset.id, models.Transaction.id != transaction.id
            ).update({models.Transaction.asset_purchase: False}, synchronize_session=False)
            asset.price = abs(transaction.amount)
            asset.purchase_date = reports.swiss_day(transaction.date)
            transaction.asset_purchase = True
    elif wanted is False or transaction.asset_id != before or not transaction.asset_id:
        transaction.asset_purchase = False
    db.commit()
    db.refresh(transaction)
    return transaction


def with_attachments(db: Session, user: models.User, transaction: models.Transaction, ids: list[str]):
    """Keep the person's pending uploads with the booking (issue #56)."""
    if ids:
        attachments.link(db, user, transaction, ids)
        db.commit()
        db.refresh(transaction)
    return transaction


def suggest_rules(db: Session, user: models.User, transaction: models.Transaction) -> None:
    """A booked receipt proposes article rules for its lines (not discounts); nothing becomes a rule by itself."""
    lines = [(i.name, i.category_id, [t.id for t in i.tags]) for i in transaction.items if i.amount > 0]
    article_rules.suggest(db, user, lines)


def create_receipt(db: Session, user: models.User, data: schemas.TransactionCreate) -> models.Transaction:
    """A booking with items (issue #56): amount and category come from the items."""
    transaction = models.Transaction(
        account_id=data.account_id,
        description=data.description,
        date=crud.to_naive_utc(data.date) if data.date else datetime.utcnow(),
        split_id=data.split_id,
        asset_id=data.asset_id,
        reference=data.reference,
    )
    items.apply(db, user, transaction, data.items or [])
    category = crud.get_category(db, transaction.category_id)
    transaction.split_shares = check_shared(db, data.split_id, data.account_id, category)
    check_asset(db, user, data.asset_id)
    db.add(transaction)
    db.flush()
    attachments.link(db, user, transaction, data.attachment_ids)
    suggest_rules(db, user, transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def update_receipt(
    db: Session, user: models.User, transaction: models.Transaction, update: schemas.TransactionUpdate
) -> models.Transaction:
    """Change a booking's items, and with them its amount and category; the split's percents stay as booked."""
    fields = update.model_fields_set
    if "description" in fields:
        transaction.description = update.description
    if update.date:
        transaction.date = crud.to_naive_utc(update.date)
    items.apply(db, user, transaction, update.items or [])
    # On a booking the bank confirmed, the receipt keeps the bank's amount (the difference becomes an item)
    reconcile.fit(db, transaction)
    category = crud.get_category(db, transaction.category_id)
    if "split_id" in fields and update.split_id != transaction.split_id:
        transaction.split_shares = check_shared(db, update.split_id, transaction.account_id, category)
        transaction.split_id = update.split_id
    if "asset_id" in fields:
        check_asset(db, user, update.asset_id, transaction.asset_id)
        transaction.asset_id = update.asset_id
    attachments.link(db, user, transaction, update.attachment_ids)
    suggest_rules(db, user, transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@router.put("/transactions/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: str,
    transaction_update: schemas.TransactionUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    flags = {"receipt_expected", "difference_accepted"} & transaction_update.model_fields_set
    if flags:
        db_transaction = crud.get_transaction(db, transaction_id)
        if not db_transaction:
            raise messages.api_error(404, "transaction_not_found")
        privacy.check_account_access(db, current_user, db_transaction.account_id, write=True)
        for flag in flags:
            setattr(db_transaction, flag, bool(getattr(transaction_update, flag)))
        db.commit()
        rest = transaction_update.model_dump(exclude_unset=True, exclude=flags)
        if not rest:
            return reconcile.annotate(db, [db_transaction])[0]
        transaction_update = schemas.TransactionUpdate(**rest)
    before = crud.get_transaction(db, transaction_id)
    asset_before = before.asset_id if before else None
    updated = change_transaction(db, current_user, transaction_id, transaction_update)
    # update_receipt links them itself, inside its own commit
    if not transaction_update.items:
        updated = with_attachments(db, current_user, updated, transaction_update.attachment_ids)
    updated = mark_purchase(db, current_user, updated, transaction_update.asset_purchase, asset_before)
    return reconcile.annotate(db, [updated])[0]


def change_transaction(
    db: Session, current_user: models.User, transaction_id: str, transaction_update: schemas.TransactionUpdate
):
    db_transaction = crud.get_transaction(db, transaction_id)
    if not db_transaction:
        raise messages.api_error(404, "transaction_not_found")
    privacy.check_account_access(db, current_user, db_transaction.account_id, write=True)

    current = crud.get_category(db, db_transaction.category_id)
    if current.type == models.CategoryType.TRANSFER:
        if transaction_update.items:
            raise messages.api_error(400, "items_need_expense_category")
        return update_transfer(db, db_transaction, transaction_update, current)
    fields = transaction_update.model_fields_set
    if transaction_update.items:
        return update_receipt(db, current_user, db_transaction, transaction_update)
    if db_transaction.items:
        if "items" not in fields:
            # Amount and category follow the items; only text and date can change on their own
            if fields - {"description", "date", "asset_purchase"}:
                raise messages.api_error(400, "edit_items_instead")
            return crud.update_transaction(
                db, db_transaction, transaction_update, current, split_shares=db_transaction.split_shares
            )
        # items: [] turns the receipt back into a plain booking with the amount and category sent
        if transaction_update.amount is None or transaction_update.category_id is None:
            raise messages.api_error(400, "edit_items_instead")
        db_transaction.items = []
    category = crud.get_category(db, transaction_update.category_id or db_transaction.category_id)
    if not category:
        raise messages.api_error(400, "category_not_found")
    if category.type == models.CategoryType.TRANSFER:
        raise messages.api_error(400, "transfers_via_settle_up")
    check_member_tag(db, transaction_update.member_id, db_transaction.account_id)
    # The split's percents are read again only when the split itself changes; otherwise the
    # booked copy stays (also when that split was deleted since)
    if "asset_id" in fields:
        check_asset(db, current_user, transaction_update.asset_id, db_transaction.asset_id)
    if "split_id" in fields and transaction_update.split_id != db_transaction.split_id:
        split_shares = check_shared(db, transaction_update.split_id, db_transaction.account_id, category)
    else:
        split_shares = db_transaction.split_shares
        if db_transaction.split_shares and category.type != models.CategoryType.EXPENSE:
            raise messages.api_error(400, "share_expenses_only")
    return crud.update_transaction(db, db_transaction, transaction_update, category, split_shares=split_shares)


def update_transfer(db: Session, db_transaction, update: schemas.TransactionUpdate, category: models.Category):
    """An imported transfer keeps its amount and category (delete and import again); Settle up stays as booked."""
    if category.system_key == SETTLE_UP:
        raise messages.api_error(400, "undo_settlement_in_common")
    changed = update.model_fields_set - {"description", "date"}
    if update.category_id == db_transaction.category_id:
        changed.discard("category_id")
    if changed:
        raise messages.api_error(400, "transfer_date_description_only")
    return crud.update_transaction(db, db_transaction, update, category)


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


# Budget Routes
@router.get("/budgets", response_model=List[schemas.Budget])
def get_budgets(
    user_id: Optional[str] = None,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Without user_id: the caller's own budgets. With user_id: someone else's they may view.
    owner = privacy.check_user_access(db, current_user, user_id) if user_id else current_user
    return [reports.budget_out(db, budget) for budget in crud.get_budgets(db, owner.id)]


@router.post("/budgets", response_model=schemas.Budget)
def create_budget(
    budget: schemas.BudgetCreate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    owner = privacy.check_user_access(db, current_user, budget.user_id, write=True) if budget.user_id else current_user
    if is_dependent(owner):
        raise messages.api_error(403, "no_budgets_without_allowance")
    if budget.category_id is not None and not crud.get_category(db, budget.category_id):
        raise messages.api_error(400, "category_not_found")
    if budget.tag_id is not None and not db.query(models.Tag).filter(models.Tag.id == budget.tag_id).first():
        raise messages.api_error(400, "tag_not_found")
    return reports.budget_out(db, crud.create_budget(db, budget=budget, user_id=owner.id))


def get_manageable_budget(db: Session, current_user, budget_id: str):
    db_budget = crud.get_budget(db, budget_id)
    owner = db.query(models.User).filter(models.User.id == db_budget.user_id).first() if db_budget else None
    # Own budgets, or those of someone who shared with EDIT
    if not owner or not privacy.can_write(privacy.access_level(db, current_user, owner)):
        raise messages.api_error(404, "budget_not_found")
    return db_budget


@router.put("/budgets/{budget_id}", response_model=schemas.Budget)
def update_budget(
    budget_id: str,
    budget_update: schemas.BudgetUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return reports.budget_out(
        db, crud.update_budget(db, get_manageable_budget(db, current_user, budget_id), budget_update)
    )


@router.delete("/budgets/{budget_id}", response_model=schemas.Budget)
def delete_budget(
    budget_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return crud.delete_budget(db, get_manageable_budget(db, current_user, budget_id))


# Share Routes
@router.get("/shares", response_model=List[schemas.Share])
def get_shares(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    # What the current user shared, and what was shared with them; not with people removed in the hub
    shares = (
        db.query(models.Share)
        .filter((models.Share.owner_id == current_user.id) | (models.Share.grantee_id == current_user.id))
        .all()
    )
    active = {u.id for u in db.query(models.User).filter(models.User.is_active.is_(True))}
    return [s for s in shares if s.owner_id in active and s.grantee_id in active]


@router.put("/shares/{grantee_id}")
def set_share(
    grantee_id: str,
    share: schemas.ShareSet,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if is_dependent(current_user):
        raise messages.api_error(403, "nothing_to_share_without_allowance")
    grantee = db.query(models.User).filter(models.User.id == grantee_id).first()
    if not grantee or grantee.role != "PARENT" or grantee.id == current_user.id:
        raise messages.api_error(400, "share_with_parent_only")
    crud.set_share(db, current_user, grantee_id, share.level)
    return {"level": share.level}
