"""Pure calculations for the common budget, yearly bills and investments."""

from datetime import date

from app import finance


def test_monthly_equivalent():
    assert finance.monthly_equivalent(1200, "YEARLY") == 100
    assert finance.monthly_equivalent(100, "YEARLY") == 8.33
    assert finance.monthly_equivalent(55.5, "MONTHLY") == 55.5


def test_next_due_this_month_later_and_next_year():
    today = date(2026, 10, 14)
    assert finance.next_due(10, today) == date(2026, 10, 1)
    assert finance.next_due(12, today) == date(2026, 12, 1)
    assert finance.next_due(1, today) == date(2027, 1, 1)
    assert finance.next_due(1, date(2026, 12, 31)) == date(2027, 1, 1)


def test_due_soon_is_within_two_months():
    today = date(2026, 11, 20)
    assert finance.is_due_soon(date(2026, 11, 1), today)
    assert finance.is_due_soon(date(2027, 1, 1), today)
    assert not finance.is_due_soon(date(2027, 2, 1), today)


def test_split_amount_rounds_and_covers_total():
    assert finance.split_amount(100, {"a": 70, "b": 30}) == {"a": 70.0, "b": 30.0}
    assert finance.split_amount(10, {"a": 33, "b": 33, "c": 34}) == {"a": 3.3, "b": 3.3, "c": 3.4}


def test_balances_two_parents():
    # Mum paid 100 at 50/50, Dad paid 40 at 70/30 (Mum 70)
    expenses = [("mum", 100, {"mum": 50, "dad": 50}), ("dad", 40, {"mum": 70, "dad": 30})]
    assert finance.balances(expenses, []) == {"mum": 22.0, "dad": -22.0}
    # Dad settles 22
    assert finance.balances(expenses, [("dad", "mum", 22)]) == {"mum": 0.0, "dad": 0.0}


def test_balances_missing_parent_counts_as_zero():
    # A third parent added after the split was made isn't in its shares
    assert finance.balances([("mum", 90, {"mum": 50, "dad": 50})], []) == {"mum": 45.0, "dad": -45.0}


def test_asset_stats():
    stats = finance.asset_stats(2400, date(2022, 10, 14), 8, 300, date(2026, 10, 14))
    assert stats["age_years"] == 4.0
    assert stats["replacement_due"] == date(2030, 10, 14)
    assert stats["is_due"] is False
    assert stats["monthly_set_aside"] == 25.0
    assert stats["total_cost"] == 2700
    assert stats["cost_per_year"] == 675.0


def test_asset_stats_new_and_leap_day():
    stats = finance.asset_stats(1000, date(2024, 2, 29), 1, 0, date(2024, 6, 1))
    assert stats["replacement_due"] == date(2025, 2, 28)
    # Less than a year old: cost per year is the total so far
    assert stats["cost_per_year"] == 1000
    assert finance.asset_stats(1000, date(2020, 1, 1), 3, 0, date(2026, 1, 1))["is_due"] is True


def test_seed_adds_missing_categories_to_existing_database():
    from app import database, models
    from app.seed import SETTLE_UP, seed_categories

    with database.SessionLocal() as db:
        db.query(models.Category).filter(models.Category.system_key == SETTLE_UP).delete()
        db.commit()
        assert seed_categories(db) == 1
        assert seed_categories(db) == 0
