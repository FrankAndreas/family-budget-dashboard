"""The common budget's money: shared expenses (booked with a split's percents) and settlements between parents."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import crud, models


def shared_transactions(db: Session) -> list[tuple[models.Transaction, str]]:
    """Every shared expense with its payer's user id, newest first."""
    rows = (
        db.query(models.Transaction, models.Account.user_id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        # Shared = booked with the split's percentages (the split itself may have been deleted since)
        .filter(func.json_type(models.Transaction.split_shares) == "object")
        .order_by(models.Transaction.date.desc())
        .all()
    )
    return [(transaction, payer) for transaction, payer in rows]


def shared_expense_rows(db: Session) -> list[tuple[str, float, dict[str, int]]]:
    # A shared refund (negative cost) lowers what the others owe
    return [(payer, crud.cost(t.amount), t.split_shares or {}) for t, payer in shared_transactions(db)]


def settlement_rows(db: Session) -> list[tuple[str, str, float]]:
    return [(s.from_user_id, s.to_user_id, s.amount) for s in db.query(models.Settlement)]
