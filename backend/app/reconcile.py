"""Receipts matched to bank rows (bank import, part 2): one booking per payment.

A bank row (an imported statement line) confirms the booking it is linked to; a receipt gives the booking its items.
The states are derived on read. They exist only on bank and savings accounts that have had a statement imported:
before that, every booking would look unconfirmed.
"""

from datetime import date, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .crud import to_cents

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
