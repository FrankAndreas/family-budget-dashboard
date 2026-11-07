"""Bookings: the checks a booking must pass and how it is saved (a request saves once, after every check)."""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from . import article_rules, attachments, crud, items, messages, models, ownership, privacy, reconcile, reports, schemas
from .privacy import is_dependent, is_parent
from .seed import SETTLE_UP


def check_member_tag(db: Session, member_id: Optional[str], account_id: str) -> None:
    """A transaction may only be tagged with a dependent child, and only on a household (parent) account."""
    if member_id is None:
        return
    member = db.query(crud.models.User).filter(crud.models.User.id == member_id).first()
    if not member or not is_dependent(member):
        raise messages.api_error(400, "tag_child_without_allowance")
    account = crud.get_account(db, account_id)
    owner = account.user if account else None
    if not owner or not is_parent(owner):
        raise messages.api_error(400, "tag_household_only")


def check_shared(db: Session, split_id: Optional[str], account_id: str, category) -> Optional[dict]:
    """A shared expense: an expense on a parent's account with an existing split. Returns the percents to keep."""
    if split_id is None:
        return None
    if category.type != models.CategoryType.EXPENSE:
        raise messages.api_error(400, "share_expenses_only")
    account = crud.get_account(db, account_id)
    owner = account.user if account else None
    if not owner or not is_parent(owner):
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
    if not asset or not ownership.visible_owner(db, current_user, asset.owner_id, asset.split_id):
        raise messages.api_error(400, "investment_not_found")
    if asset.archived_on and asset_id != linked:
        raise messages.api_error(400, "investment_archived")


def create(db: Session, user: models.User, transaction: schemas.TransactionCreate) -> models.Transaction:
    """A new booking, plain or with items, saved once every check passed."""
    privacy.check_account_access(db, user, transaction.account_id, write=True)
    if transaction.items is not None:
        receipt = create_receipt(db, user, transaction)
        return saved(db, mark_purchase(db, user, receipt, transaction.asset_purchase or None))
    # Without items the schema requires both (TransactionCreate.plain_needs_amount_and_category)
    assert transaction.category_id is not None and transaction.amount is not None
    category = crud.get_category(db, transaction.category_id)
    if not category:
        raise messages.api_error(400, "category_not_found")
    if category.type == models.CategoryType.TRANSFER:
        raise messages.api_error(400, "transfers_via_settle_up")
    check_member_tag(db, transaction.member_id, transaction.account_id)
    split_shares = check_shared(db, transaction.split_id, transaction.account_id, category)
    check_asset(db, user, transaction.asset_id)
    created = crud.create_transaction(
        db, transaction=transaction, category=category, split_shares=split_shares, commit=False
    )
    created = with_attachments(db, user, created, transaction.attachment_ids)
    return saved(db, mark_purchase(db, user, created, transaction.asset_purchase or None))


def update(
    db: Session, user: models.User, transaction_id: str, transaction_update: schemas.TransactionUpdate
) -> models.Transaction:
    """A change to a booking, saved once every check passed. The reconciliation marks alone need only write access."""
    flags = {"receipt_expected", "difference_accepted"} & transaction_update.model_fields_set
    if flags:
        db_transaction = crud.get_transaction(db, transaction_id)
        if not db_transaction:
            raise messages.api_error(404, "transaction_not_found")
        privacy.check_account_access(db, user, db_transaction.account_id, write=True)
        for flag in flags:
            setattr(db_transaction, flag, bool(getattr(transaction_update, flag)))
        rest = transaction_update.model_dump(exclude_unset=True, exclude=flags)
        if not rest:
            return saved(db, db_transaction)
        transaction_update = schemas.TransactionUpdate(**rest)
    before = crud.get_transaction(db, transaction_id)
    asset_before = before.asset_id if before else None
    updated = change_transaction(db, user, transaction_id, transaction_update)
    # update_receipt links them itself
    if not transaction_update.items:
        updated = with_attachments(db, user, updated, transaction_update.attachment_ids)
    updated = mark_purchase(db, user, updated, transaction_update.asset_purchase, asset_before)
    return saved(db, updated)


def saved(db: Session, transaction: models.Transaction) -> models.Transaction:
    """A booking request saves once, after every check passed: a rejected change leaves nothing half saved (the
    helpers below only flush; an error closes the session, which drops what was flushed)."""
    db.commit()
    db.refresh(transaction)
    return transaction


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
        # Money back can't be what bought it
        if transaction.amount > 0:
            raise messages.api_error(400, "refund_no_purchase")
        asset = db.query(models.Asset).filter(models.Asset.id == transaction.asset_id).one()
        if not ownership.visible_owner(db, user, asset.owner_id, asset.split_id, write=True):
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
    db.flush()
    return transaction


def with_attachments(db: Session, user: models.User, transaction: models.Transaction, ids: list[str]):
    """Keep the person's pending uploads with the booking (issue #56)."""
    if ids:
        attachments.link(db, user, transaction, ids)
        db.flush()
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
    db.flush()
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
    db.flush()
    return transaction


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
                db, db_transaction, transaction_update, current, split_shares=db_transaction.split_shares, commit=False
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
    return crud.update_transaction(
        db, db_transaction, transaction_update, category, split_shares=split_shares, commit=False
    )


def update_transfer(db: Session, db_transaction, update: schemas.TransactionUpdate, category: models.Category):
    """An imported transfer keeps its amount and category (delete and import again); Settle up stays as booked."""
    if category.system_key == SETTLE_UP:
        raise messages.api_error(400, "undo_settlement_in_common")
    changed = update.model_fields_set - {"description", "date"}
    if update.category_id == db_transaction.category_id:
        changed.discard("category_id")
    if changed:
        raise messages.api_error(400, "transfer_date_description_only")
    return crud.update_transaction(db, db_transaction, update, category, commit=False)
