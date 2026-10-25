"""Budgets' spending and the Analytics numbers, calculated on the server in Swiss time.

A scope is one person's money: their accounts only. Transfers never count; income and expenses follow the
category type.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, selectinload

from . import auth, database, finance, i18n, models, privacy

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


@dataclass(frozen=True)
class Line:
    """What counts: a plain booking, or one item of a receipt (issue #56). amount > 0 is a cost or an income;
    a discount item is negative and lowers its category."""

    date: datetime
    amount: float
    type: models.CategoryType
    category: models.Category
    person_id: Optional[str] = None
    tag_ids: frozenset[str] = frozenset()
    member_id: Optional[str] = None


def lines(db: Session, owner_id: str, since: Optional[date]) -> list[Line]:
    """The owner's income and expenses (no transfers) from a Swiss day on: one line per plain booking, one per item."""
    query = (
        db.query(models.Transaction, models.Category)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .join(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(models.Account.user_id == owner_id, models.Category.type.in_([INCOME, EXPENSE]))
        .options(
            selectinload(models.Transaction.items).selectinload(models.TransactionItem.category),
            selectinload(models.Transaction.items).selectinload(models.TransactionItem.tags),
        )
    )
    if since:
        query = query.filter(models.Transaction.date >= utc_start(since))
    # A booking linked to an investment with a tag counts under that tag (the purchase and its follow-up costs)
    asset_tags: dict[str, str] = {
        asset_id: tag_id
        for asset_id, tag_id in db.query(models.Asset.id, models.Asset.tag_id).filter(models.Asset.tag_id.isnot(None))
        if tag_id
    }
    result = []
    for transaction, category in query.all():
        via_asset = frozenset([asset_tags[transaction.asset_id]] if transaction.asset_id in asset_tags else [])
        if not transaction.items:
            result.append(
                Line(
                    transaction.date,
                    abs(transaction.amount),
                    category.type,
                    category,
                    member_id=transaction.member_id,
                    tag_ids=via_asset,
                )
            )
            continue
        for item in transaction.items:
            result.append(
                Line(
                    transaction.date,
                    item.amount,
                    item.category.type,
                    item.category,
                    person_id=item.person_id,
                    tag_ids=frozenset(t.id for t in item.tags) | via_asset,
                )
            )
    return result


def budget_out(db: Session, budget: models.Budget) -> dict:
    day = today()
    since = month_start(day) if budget.period == "MONTHLY" else date(day.year, 1, 1)
    # A tag budget counts every line carrying the tag (an item with several tags counts in each of their budgets)
    spent = cents(
        sum(
            line.amount
            for line in lines(db, budget.user_id, since)
            if line.type == EXPENSE
            and (line.category.id == budget.category_id if budget.tag_id is None else budget.tag_id in line.tag_ids)
        )
    )
    percentage = round(spent / budget.limit * 100, 1) if budget.limit else 0.0
    return {
        "id": budget.id,
        "user_id": budget.user_id,
        "category_id": budget.category_id,
        "tag_id": budget.tag_id,
        "limit": budget.limit,
        "period": budget.period,
        "spent": spent,
        "percentage": percentage,
    }


def set_aside_by_tag(db: Session, owner_id: str) -> dict[str, float]:
    """Per tag: what the owner sets aside each month for the active investments with it (their share of common ones)."""
    result: dict[str, float] = defaultdict(float)
    splits = {s.id: s.shares or {} for s in db.query(models.Split)}
    for asset in db.query(models.Asset).filter(models.Asset.tag_id.isnot(None), models.Asset.archived_on.is_(None)):
        if not asset.tag_id:
            continue
        monthly = finance.cents(asset.price / (asset.lifespan_years * 12))
        if asset.split_id:
            result[asset.tag_id] += finance.split_amount(monthly, splits.get(asset.split_id, {})).get(owner_id, 0.0)
        elif asset.owner_id == owner_id:
            result[asset.tag_id] += monthly
    return {tag_id: amount for tag_id, amount in result.items() if amount}


def summary(db: Session, owner: models.User, period: str, day: date) -> dict:
    start = range_start(period, day)
    six_months = month_start(day, 5)
    rows = lines(db, owner.id, None if start is None else min(start, six_months))
    totals = {INCOME: 0.0, EXPENSE: 0.0}
    by_category: dict[str, list] = {}
    by_child: dict[str, float] = defaultdict(float)
    # An item counts in full under each of its tags, so these totals overlap and are never added up
    by_tag: dict[str, float] = defaultdict(float)
    by_person: dict[str, float] = defaultdict(float)
    months = {month_start(day, back).strftime("%Y-%m"): {INCOME: 0.0, EXPENSE: 0.0} for back in range(5, -1, -1)}
    first = month_start(day)
    days = {}
    current = first
    while current.month == first.month:
        days[current.isoformat()] = {INCOME: 0.0, EXPENSE: 0.0}
        current = date.fromordinal(current.toordinal() + 1)
    dependents = {
        u.id for u in db.query(models.User).filter(models.User.role == models.UserRole.CHILD) if not u.has_allowance
    }
    for line in rows:
        local = swiss_day(line.date)
        if start is None or local >= start:
            totals[line.type] += line.amount
            if line.type == EXPENSE:
                by_category.setdefault(line.category.id, [i18n.category_name(line.category), 0.0])[1] += line.amount
                child = line.member_id or (line.person_id if line.person_id in dependents else None)
                if child:
                    by_child[child] += line.amount
                for tag_id in line.tag_ids:
                    by_tag[tag_id] += line.amount
                if line.person_id:
                    by_person[line.person_id] += line.amount
        if local.strftime("%Y-%m") in months:
            months[local.strftime("%Y-%m")][line.type] += line.amount
        if local.isoformat() in days:
            days[local.isoformat()][line.type] += line.amount
    set_aside = set_aside_by_tag(db, owner.id)
    for tag_id in set_aside:
        by_tag.setdefault(tag_id, 0.0)
    people = set(by_child) | set(by_person)
    names = {u.id: u.username for u in db.query(models.User).filter(models.User.id.in_(list(people)))}
    tags = {t.id: t for t in db.query(models.Tag).filter(models.Tag.id.in_(list(by_tag)))}
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
        "by_tag": sorted(
            (
                {
                    "tag_id": tid,
                    "name": tags[tid].name,
                    "icon": tags[tid].icon,
                    "amount": cents(a),
                    "set_aside": cents(set_aside.get(tid, 0.0)),
                }
                for tid, a in by_tag.items()
                if tid in tags
            ),
            key=lambda row: -row["amount"],
        ),
        "by_person": sorted(
            ({"person_id": pid, "name": names.get(pid, ""), "amount": cents(a)} for pid, a in by_person.items()),
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
