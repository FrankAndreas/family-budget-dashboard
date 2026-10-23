"""Receipts matched to bank rows (bank import, part 2): one booking per payment.

A bank row (an imported statement line) confirms the booking it is linked to; a receipt gives the booking its items.
The states are derived on read. They exist only on bank and savings accounts that have had a statement imported:
before that, every booking would look unconfirmed.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, crud, database, messages, models, privacy, schemas
from .crud import to_cents
from .seed import SETTLE_UP

router = APIRouter()

# Amounts this close still match, and a receipt's difference up to this doesn't warn
TOLERANCE = 1.00
# A booking without a bank row is "no payment found" once a statement reaches this many days past its date
NO_PAYMENT_DAYS = 7
ZURICH = ZoneInfo("Europe/Zurich")
WITH_STATES = (models.AccountType.BANK, models.AccountType.SAVINGS)


def swiss_day(transaction: models.Transaction) -> date:
    return transaction.date.replace(tzinfo=timezone.utc).astimezone(ZURICH).date()


def covered_until(db: Session, account_id: str) -> Optional[date]:
    """The date of the account's latest imported bank line; None before the first import."""
    latest: Optional[date] = (
        db.query(func.max(models.BankRow.booked_on)).filter(models.BankRow.account_id == account_id).scalar()
    )
    return latest


def state(transaction: models.Transaction, account: models.Account, covered: Optional[date]) -> dict:
    confirmation = None
    if account.type in WITH_STATES and covered is not None:
        paid = to_cents(sum(r.amount for r in transaction.bank_rows))
        if transaction.bank_rows:
            confirmation = "confirmed" if paid == to_cents(transaction.amount) else "partly_paid"
        elif covered >= swiss_day(transaction) + timedelta(days=NO_PAYMENT_DAYS):
            confirmation = "no_payment"
        else:
            confirmation = "not_confirmed"
    return {
        "confirmation": confirmation,
        "receipt_missing": bool(transaction.receipt_expected) and not transaction.attachments,
        "differs": abs(transaction.difference or 0) > TOLERANCE and not transaction.difference_accepted,
    }


def is_open(found: dict) -> bool:
    return (
        found["confirmation"] in ("not_confirmed", "no_payment", "partly_paid")
        or found["receipt_missing"]
        or found["differs"]
    )


def annotate(db: Session, transactions: list[models.Transaction]) -> list[models.Transaction]:
    """Each booking gets its state (read by the API schema)."""
    accounts: dict[str, tuple[models.Account, Optional[date]]] = {}
    for transaction in transactions:
        if transaction.account_id not in accounts:
            account = db.get(models.Account, transaction.account_id)
            assert account is not None, "a booking belongs to an account"
            accounts[transaction.account_id] = (account, covered_until(db, transaction.account_id))
        account, covered = accounts[transaction.account_id]
        transaction.state = state(transaction, account, covered)  # type: ignore[attr-defined]
    return transactions


def unlinked_rows(db: Session, account_id: str) -> int:
    return (
        db.query(models.BankRow)
        .filter(models.BankRow.account_id == account_id, models.BankRow.transaction_id.is_(None))
        .count()
    )


def summary(db: Session, account: models.Account) -> dict:
    """Open points (open bookings and bank lines without booking) and the sum of the unconfirmed bookings."""
    covered = covered_until(db, account.id)
    if account.type not in WITH_STATES or covered is None:
        return {"open_points": 0, "not_confirmed": 0.0}
    bookings = db.query(models.Transaction).filter(models.Transaction.account_id == account.id).all()
    found = [(t, state(t, account, covered)) for t in bookings]
    unconfirmed = sum(t.amount for t, s in found if s["confirmation"] in ("not_confirmed", "no_payment"))
    return {
        "open_points": sum(is_open(s) for _, s in found) + unlinked_rows(db, account.id),
        "not_confirmed": to_cents(unconfirmed) + 0.0,
    }


def fit(db: Session, transaction: models.Transaction) -> None:
    """A booking with bank rows takes the bank's amount. With items, the difference to the receipt's total becomes an
    item of its own ("Difference", in the booking's main category); a plain booking only within TOLERANCE. The caller
    commits."""
    if not transaction.bank_rows:
        return
    target = to_cents(sum(r.amount for r in transaction.bank_rows))
    if not transaction.items:
        if abs(target - transaction.amount) <= TOLERANCE:
            transaction.amount = target
        return
    if target >= 0:
        # Items are costs: money coming in can't be a receipt's payment
        return
    total = to_cents(sum(i.amount for i in transaction.items))
    difference = to_cents(-target - total)
    if difference:
        transaction.items.append(
            models.TransactionItem(
                position=len(transaction.items),
                name=messages.text("difference_item"),
                amount=difference,
                category_id=transaction.category_id,
            )
        )
        transaction.amount = target
        transaction.difference = difference
    else:
        transaction.difference = None
    db.flush()


def get_row(db: Session, row_id: str) -> models.BankRow:
    row = db.get(models.BankRow, row_id)
    if not row:
        raise messages.api_error(404, "bank_row_not_found")
    return row


def writable_booking(db: Session, user: models.User, transaction_id: str) -> models.Transaction:
    transaction: Optional[models.Transaction] = crud.get_transaction(db, transaction_id)
    if not transaction:
        raise messages.api_error(404, "transaction_not_found")
    privacy.check_account_access(db, user, transaction.account_id, write=True)
    return transaction


@router.post("/transactions/{transaction_id}/bank-rows/{row_id}", response_model=schemas.Transaction)
def link_row(
    transaction_id: str,
    row_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    """Link a bank line to a booking (moving it from the one it had)."""
    transaction = writable_booking(db, current_user, transaction_id)
    row = get_row(db, row_id)
    if row.account_id != transaction.account_id:
        raise messages.api_error(400, "bank_row_other_account")
    row.transaction_id = transaction.id
    db.flush()
    db.refresh(transaction)
    fit(db, transaction)
    db.commit()
    db.refresh(transaction)
    return annotate(db, [transaction])[0]


@router.delete("/transactions/{transaction_id}/bank-rows/{row_id}", response_model=schemas.Transaction)
def unlink_row(
    transaction_id: str,
    row_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    transaction = writable_booking(db, current_user, transaction_id)
    row = get_row(db, row_id)
    if row.transaction_id != transaction.id:
        raise messages.api_error(404, "bank_row_not_found")
    row.transaction_id = None
    db.commit()
    db.refresh(transaction)
    return annotate(db, [transaction])[0]


class BankRowListed(schemas.BankRowOut):
    transaction_id: Optional[str] = None


@router.get("/accounts/{account_id}/bank-rows", response_model=list[BankRowListed])
def list_rows(
    account_id: str,
    unlinked: bool = False,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    privacy.check_account_access(db, current_user, account_id)
    query = db.query(models.BankRow).filter(models.BankRow.account_id == account_id)
    if unlinked:
        query = query.filter(models.BankRow.transaction_id.is_(None))
    return query.order_by(models.BankRow.booked_on.desc(), models.BankRow.imported_at.desc()).all()


class BookRow(BaseModel):
    category_id: str


@router.post("/bank-rows/{row_id}/book", response_model=schemas.Transaction)
def book_row(
    row_id: str,
    body: BookRow,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    """A plain booking from a bank line without one (its booking was deleted, or it was unlinked)."""
    row = get_row(db, row_id)
    privacy.check_account_access(db, current_user, row.account_id, write=True)
    if row.transaction_id:
        raise messages.api_error(400, "bank_row_linked")
    category = crud.get_category(db, body.category_id)
    if not category:
        raise messages.api_error(404, "category_not_found")
    if category.system_key == SETTLE_UP:
        raise messages.api_error(400, "settle_up_not_importable")
    expected = models.CategoryType.EXPENSE if row.amount < 0 else models.CategoryType.INCOME
    if category.type not in (expected, models.CategoryType.TRANSFER):
        raise messages.api_error(400, "bank_row_category_sign")
    data = schemas.TransactionCreate(
        account_id=row.account_id,
        category_id=category.id,
        # A transfer keeps its sign (crud.signed_amount); income and expenses take it from the category
        amount=row.amount,
        description=row.text,
        date=datetime.combine(row.booked_on, time(12)),
    )
    transaction = crud.create_transaction(db, data, category, commit=False)
    row.transaction_id = transaction.id
    db.commit()
    db.refresh(transaction)
    return annotate(db, [transaction])[0]
