"""Month check for clearing accounts (Migros, ...): money comes in by transfer and goes out by receipts, so each
completed month's own bookings should add up to 0. The gap is booked once as "Unknown expense" (money without
receipts) or "Other Income" (receipts paid partly by gift cards or vouchers)."""

import calendar
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import auth, crud, database, models, privacy, schemas
from .seed import OTHER_INCOME, UNKNOWN_EXPENSE, system_category

router = APIRouter()

ZURICH = ZoneInfo("Europe/Zurich")
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def month_of(value: datetime) -> str:
    """The Swiss calendar month (YYYY-MM) of a stored date (naive UTC)."""
    return value.replace(tzinfo=timezone.utc).astimezone(ZURICH).strftime("%Y-%m")


def reference(month: str) -> str:
    return f"month-check:{month}"


def clearing_account(db: Session, current_user, account_id: str, write: bool = False) -> models.Account:
    account = privacy.check_account_access(db, current_user, account_id, write=write)
    if account.type != models.AccountType.CLEARING:
        raise HTTPException(status_code=400, detail="Only clearing accounts have a month check")
    return account


def months(db: Session, account: models.Account) -> dict:
    """Per Swiss month: money in, money out, their difference, and whether its month-check booking exists."""
    sums: defaultdict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    references = set()
    for t in db.query(models.Transaction).filter(models.Transaction.account_id == account.id):
        sums[month_of(t.date)][0 if t.amount >= 0 else 1] += abs(t.amount)
        references.add(t.reference)
    return {
        month: {
            "month": month,
            "money_in": crud.to_cents(money_in),
            "money_out": crud.to_cents(money_out),
            # Rounded to cents, so float noise counts as 0
            "difference": crud.to_cents(money_in - money_out) + 0.0,
            "booked": reference(month) in references,
        }
        for month, (money_in, money_out) in sums.items()
    }


def current_month() -> str:
    return datetime.now(ZURICH).strftime("%Y-%m")


@router.get("/accounts/{account_id}/month-check")
def get_month_check(
    account_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> List[dict]:
    account = clearing_account(db, current_user, account_id)
    open_months = [m for m in months(db, account).values() if m["month"] < current_month() and m["difference"]]
    return sorted(open_months, key=lambda m: m["month"], reverse=True)


@router.post("/accounts/{account_id}/month-check/{month}", response_model=schemas.Transaction)
def book_month_check(
    account_id: str,
    month: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    account = clearing_account(db, current_user, account_id, write=True)
    if not MONTH.match(month):
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM")
    if month >= current_month():
        raise HTTPException(status_code=400, detail="Only completed months can be checked")
    row = months(db, account).get(month)
    if not row or not row["difference"]:
        raise HTTPException(status_code=400, detail="This month adds up already")
    if row["booked"]:
        raise HTTPException(
            status_code=409, detail="Already booked; delete the month-check booking to book the new difference"
        )
    category = system_category(db, UNKNOWN_EXPENSE if row["difference"] > 0 else OTHER_INCOME)
    year, number = int(month[:4]), int(month[5:])
    transaction = schemas.TransactionCreate(
        account_id=account.id,
        category_id=category.id,
        amount=abs(row["difference"]),
        description=f"Month check {calendar.month_name[number]} {year}",
        reference=reference(month),
        # Noon UTC on the last day: that day in Switzerland too (same as a date-only import)
        date=datetime(year, number, calendar.monthrange(year, number)[1], 12, tzinfo=timezone.utc),
    )
    return crud.create_transaction(db, transaction, category)
