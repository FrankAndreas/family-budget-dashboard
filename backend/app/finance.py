"""Calculations for the common budget, yearly bills and investments. Pure functions, no database."""

import calendar
from datetime import date
from typing import Optional


def cents(value: float) -> float:
    return round(value, 2)


def monthly_equivalent(amount: float, frequency: str) -> float:
    return cents(amount / 12 if frequency == "YEARLY" else amount)


def next_due(due_month: int, today: date) -> date:
    """First day of the coming due month; the current month counts as coming."""
    year = today.year if due_month >= today.month else today.year + 1
    return date(year, due_month, 1)


def is_due_soon(due: date, today: date) -> bool:
    """Due in this month or the next two."""
    months_ahead = (due.year - today.year) * 12 + due.month - today.month
    return 0 <= months_ahead <= 2


def split_amount(amount: float, shares: dict[str, int]) -> dict[str, float]:
    return {user_id: cents(amount * percent / 100) for user_id, percent in shares.items()}


def balances(
    expenses: list[tuple[str, float, dict[str, int]]], settlements: list[tuple[str, str, float]]
) -> dict[str, float]:
    """Net position per parent: positive = the others owe them, negative = they owe.

    expenses: (payer_id, amount paid, split percents per parent); settlements: (from_id, to_id, amount).
    A parent missing from a split's percents has a share of 0.
    """
    net: dict[str, float] = {}
    for payer, amount, shares in expenses:
        net.setdefault(payer, 0.0)
        for user_id, share in split_amount(amount, shares).items():
            if user_id == payer:
                continue
            net[payer] += share
            net[user_id] = net.get(user_id, 0.0) - share
    for from_id, to_id, amount in settlements:
        net[from_id] = net.get(from_id, 0.0) + amount
        net[to_id] = net.get(to_id, 0.0) - amount
    # + 0.0 turns -0.0 into 0.0, so a settled balance shows without a minus
    return {user_id: cents(value) + 0.0 for user_id, value in net.items()}


def add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February in a non-leap year
        return day.replace(year=day.year + years, day=28)


def add_months(day: date, months: int) -> date:
    years, month = divmod(day.month - 1 + months, 12)
    year, month = day.year + years, month + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def asset_plan(
    price: float,
    purchase_date: date,
    lifespan_years: int,
    today: date,
    lease: Optional[tuple[float, int, float]] = None,
) -> dict:
    """What an investment needs each month. Bought: the price spread over the lifespan. Leased (rate, months, final
    payment): during the term the rate plus the buy-out saved up over the term; afterwards, like a bought car, what it
    cost in all (down payment, rates, buy-out) spread over the rest of its lifespan, for the next one."""
    if not lease:
        set_aside = cents(price / (lifespan_years * 12))
        return {"monthly_set_aside": set_aside, "monthly_rate": 0.0, "monthly_load": set_aside, "lease_end": None}
    rate, months, final = lease
    lease_end = add_months(purchase_date, months)
    if today < lease_end:
        set_aside, monthly_rate = cents(final / months), rate
    else:
        set_aside, monthly_rate = cents((price + rate * months + final) / (lifespan_years * 12 - months)), 0.0
    return {
        "monthly_set_aside": set_aside,
        "monthly_rate": monthly_rate,
        "monthly_load": cents(set_aside + monthly_rate),
        "lease_end": lease_end,
    }


def asset_stats(
    price: float,
    purchase_date: date,
    lifespan_years: int,
    follow_up_costs: float,
    today: date,
    lease: Optional[tuple[float, int, float]] = None,
) -> dict:
    # A purchase date in the future means the investment is planned, not bought yet: age 0
    planned = purchase_date > today
    age_years = 0.0 if planned else round((today - purchase_date).days / 365.25, 1)
    replacement_due = add_years(purchase_date, lifespan_years)
    total_cost = cents(price + follow_up_costs)
    return {
        "age_years": age_years,
        "planned": planned,
        "replacement_due": replacement_due,
        "is_due": today >= replacement_due,
        **asset_plan(price, purchase_date, lifespan_years, today, lease),
        "total_cost": total_cost,
        "cost_per_year": cents(total_cost / max(age_years, 1)),
    }
