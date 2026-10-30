"""A dependent child's own costs, read-only (spec 2026-10-30, part B).

A child without Jugendlohn has no money of their own: their costs are household bookings tagged with them, or receipt
items for them. They see those, by month and category, and nothing else: no receipts (a receipt shows the whole
family's shopping), no accounts, not who paid."""

import re
from collections import defaultdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from . import auth, database, i18n, messages, models
from .reports import EXPENSE, cents, swiss_day, today, utc_start

router = APIRouter()

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def is_dependent(user: models.User) -> bool:
    return user.role == models.UserRole.CHILD and not user.has_allowance


def _child_text(booking: models.Transaction) -> str:
    """What the child reads for a plain booking (issue #132): a text a parent typed in the app; an imported line (a
    bank statement's text can hold a payer's name or account details) shows its category instead."""
    if booking.reference or booking.bank_rows:
        return i18n.category_name(booking.category)
    return booking.description or ""


def year_costs(db: Session, child_id: str, year: int) -> list[dict]:
    """The child's costs in a year: a tagged plain booking, or each receipt item for them (as the reports count)."""
    found = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.date >= utc_start(date(year, 1, 1)),
            models.Transaction.date < utc_start(date(year + 1, 1, 1)),
            or_(
                models.Transaction.member_id == child_id,
                models.Transaction.items.any(models.TransactionItem.person_id == child_id),
            ),
        )
        .options(
            selectinload(models.Transaction.category),
            selectinload(models.Transaction.bank_rows),
            selectinload(models.Transaction.items).selectinload(models.TransactionItem.category),
        )
        .all()
    )
    result = []
    for booking in found:
        day = swiss_day(booking.date)
        if not booking.items:
            if booking.category and booking.category.type == EXPENSE:
                result.append((day, _child_text(booking), booking.category, abs(booking.amount)))
            continue
        for item in booking.items:
            if item.person_id == child_id and item.category.type == EXPENSE:
                result.append((day, item.name, item.category, item.amount))
    return [
        {
            "date": day.isoformat(),
            "description": text,
            "category": i18n.category_name(category),
            "amount": cents(amount),
        }
        for day, text, category, amount in result
    ]


@router.get("/my-costs")
def my_costs(
    month: Optional[str] = Query(default=None, pattern=MONTH.pattern),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if not is_dependent(current_user):
        raise messages.api_error(403, "my_costs_dependent_only")
    month = month or today().strftime("%Y-%m")
    rows = year_costs(db, current_user.id, int(month[:4]))
    in_month = [row for row in rows if row["date"].startswith(month)]
    by_category: dict[str, float] = defaultdict(float)
    for row in in_month:
        by_category[row["category"]] += row["amount"]
    return {
        "month": month,
        "month_total": cents(sum(row["amount"] for row in in_month)),
        "year_total": cents(sum(row["amount"] for row in rows)),
        "by_category": [
            {"category": name, "amount": cents(amount)}
            for name, amount in sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        # Newest first; on the same day in the order they were booked
        "bookings": sorted(in_month, key=lambda row: row["date"], reverse=True),
    }
