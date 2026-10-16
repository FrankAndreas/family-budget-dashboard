"""Budgets' spending and the Analytics numbers, calculated on the server in Swiss time.

A scope is one person's money: their accounts only. Transfers never count; income and expenses follow the
category type.
"""

from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from . import auth, database, models, privacy

router = APIRouter()

ZURICH = ZoneInfo("Europe/Zurich")
Range = Literal["month", "3months", "year", "all"]
INCOME, EXPENSE = models.CategoryType.INCOME, models.CategoryType.EXPENSE


def today() -> date:
    return datetime.now(ZURICH).date()


def utc_start(day: date) -> datetime:
    """Midnight of a Swiss day, as a stored (naive UTC) date."""
    return datetime.combine(day, time(), ZURICH).astimezone(timezone.utc).replace(tzinfo=None)


def swiss_day(value: datetime) -> date:
    return value.replace(tzinfo=timezone.utc).astimezone(ZURICH).date()


def month_start(day: date, back: int = 0) -> date:
    months = day.year * 12 + day.month - 1 - back
    return date(months // 12, months % 12 + 1, 1)


def range_start(period: str, day: date) -> Optional[date]:
    return {"month": month_start(day), "3months": month_start(day, 2), "year": date(day.year, 1, 1)}.get(period)


def cents(value: float) -> float:
    return round(value + 0.0, 2)


def bookings(db: Session, owner_id: str, since: Optional[date]) -> list[tuple[models.Transaction, models.Category]]:
    """The owner's income and expenses (no transfers) from a Swiss day on."""
    query = (
        db.query(models.Transaction, models.Category)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .join(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(models.Account.user_id == owner_id, models.Category.type.in_([INCOME, EXPENSE]))
    )
    if since:
        query = query.filter(models.Transaction.date >= utc_start(since))
    return [(transaction, category) for transaction, category in query.all()]


def budget_out(db: Session, budget: models.Budget) -> dict:
    day = today()
    since = month_start(day) if budget.period == "MONTHLY" else date(day.year, 1, 1)
    spent = cents(
        sum(
            abs(t.amount)
            for t, c in bookings(db, budget.user_id, since)
            if c.type == EXPENSE and c.id == budget.category_id
        )
    )
    percentage = round(spent / budget.limit * 100, 1) if budget.limit else 0.0
    return {
        "id": budget.id,
        "user_id": budget.user_id,
        "category_id": budget.category_id,
        "limit": budget.limit,
        "period": budget.period,
        "spent": spent,
        "percentage": percentage,
    }


def summary(db: Session, owner: models.User, period: str, day: date) -> dict:
    start = range_start(period, day)
    six_months = month_start(day, 5)
    rows = bookings(db, owner.id, None if start is None else min(start, six_months))
    totals = {INCOME: 0.0, EXPENSE: 0.0}
    by_category: dict[str, list] = {}
    by_child: dict[str, float] = defaultdict(float)
    months = {month_start(day, back).strftime("%Y-%m"): {INCOME: 0.0, EXPENSE: 0.0} for back in range(5, -1, -1)}
    first = month_start(day)
    days = {}
    current = first
    while current.month == first.month:
        days[current.isoformat()] = {INCOME: 0.0, EXPENSE: 0.0}
        current = date.fromordinal(current.toordinal() + 1)
    for transaction, category in rows:
        local = swiss_day(transaction.date)
        amount = abs(transaction.amount)
        if start is None or local >= start:
            totals[category.type] += amount
            if category.type == EXPENSE:
                by_category.setdefault(category.id, [category.name, 0.0])[1] += amount
                if transaction.member_id:
                    by_child[transaction.member_id] += amount
        if local.strftime("%Y-%m") in months:
            months[local.strftime("%Y-%m")][category.type] += amount
        if local.isoformat() in days:
            days[local.isoformat()][category.type] += amount
    names = {u.id: u.username for u in db.query(models.User).filter(models.User.id.in_(list(by_child)))}
    is_parent = owner.role == models.UserRole.PARENT
    return {
        "range": period,
        "income": cents(totals[INCOME]),
        "expenses": cents(totals[EXPENSE]),
        "by_category": sorted(
            (
                {"category_id": cid, "name": name, "amount": cents(amount)}
                for cid, (name, amount) in by_category.items()
            ),
            key=lambda row: -row["amount"],
        ),
        "by_child": sorted(
            (
                ({"member_id": mid, "name": names.get(mid, ""), "amount": cents(a)} for mid, a in by_child.items())
                if is_parent
                else []
            ),
            key=lambda row: -row["amount"],
        ),
        "months": [{"month": m, "income": cents(v[INCOME]), "expenses": cents(v[EXPENSE])} for m, v in months.items()],
        "days": [{"date": d, "income": cents(v[INCOME]), "expenses": cents(v[EXPENSE])} for d, v in days.items()],
    }


@router.get("/reports/summary")
def get_summary(
    user_id: Optional[str] = None,
    period: Range = Query("month", alias="range"),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    owner = privacy.check_user_access(db, current_user, user_id) if user_id else current_user
    return summary(db, owner, period, today())
