"""A dependent child sees their own costs, and nothing else (spec 2026-10-30, part B)."""

from datetime import datetime

import pytest

import fake_hub
from helpers import BASE_URL, add_member, add_transaction, bearer, category_id, create_account, register

from app import database, models


def costs(client, headers, month="2026-03"):
    return client.get(f"{BASE_URL}/my-costs", params={"month": month}, headers=headers)


@pytest.fixture
def kim(client):
    """Mum's household bookings, some for the dependent child Kim."""
    mum = register(client, "mum")
    kim_id = add_member(client, "Kim")
    account = create_account(client, mum)
    clothing, groceries = category_id(client, "Clothing"), category_id(client, "Groceries")

    def book(category, amount, day, tagged=True, description="Kauf"):
        extra = {"member_id": kim_id} if tagged else {}
        add_transaction(
            client, mum, account, category, amount, date=f"{day}T12:00:00", description=description, **extra
        )

    book(clothing, 80, "2026-03-10", description="Jacke")
    book(groceries, 20, "2026-03-15", description="Znüni")
    book(clothing, 30, "2026-01-05", description="Mütze")
    book(groceries, 99, "2026-03-01", tagged=False)
    # A receipt whose items name who they were for: a pair of trousers for Kim, with a discount, and bread for all
    with database.SessionLocal() as db:
        cat = {c.name: c.id for c in db.query(models.Category)}
        booking = models.Transaction(
            account_id=account, category_id=cat["Clothing"], amount=-73.40, date=datetime(2026, 3, 20, 11)
        )
        booking.items = [
            models.TransactionItem(
                position=0, name="Velo-Hose", amount=79.90, category_id=cat["Clothing"], person_id=kim_id
            ),
            models.TransactionItem(
                position=1, name="Rabatt", amount=-10.00, category_id=cat["Clothing"], person_id=kim_id
            ),
            models.TransactionItem(position=2, name="Brot", amount=3.50, category_id=cat["Groceries"]),
        ]
        db.add(booking)
        db.commit()
    return {"mum": mum, "headers": bearer(fake_hub.token("Kim")), "account": account}


def test_month_and_year_totals(client, kim):
    found = costs(client, kim["headers"]).json()
    assert found["month"] == "2026-03"
    assert found["month_total"] == 169.90
    assert found["year_total"] == 199.90


def test_by_category_largest_first(client, kim):
    assert costs(client, kim["headers"]).json()["by_category"] == [
        {"category": "Clothing", "amount": 149.90},
        {"category": "Groceries", "amount": 20.0},
    ]


def test_bookings_newest_first(client, kim):
    bookings = costs(client, kim["headers"]).json()["bookings"]
    assert [(b["date"], b["description"], b["amount"]) for b in bookings] == [
        ("2026-03-20", "Velo-Hose", 79.90),
        ("2026-03-20", "Rabatt", -10.0),
        ("2026-03-15", "Znüni", 20.0),
        ("2026-03-10", "Jacke", 80.0),
    ]


def test_no_attachment_or_account_fields(client, kim):
    for booking in costs(client, kim["headers"]).json()["bookings"]:
        assert set(booking) == {"date", "description", "category", "amount"}


def test_child_cannot_change_anything(client, kim):
    child = kim["headers"]
    for method, path, body in [
        ("POST", "/accounts", {"name": "Mine", "type": "CASH"}),
        ("PUT", f"/accounts/{kim['account']}", {"name": "x"}),
        ("GET", "/accounts", None),
        ("GET", "/users", None),
        ("GET", f"/accounts/{kim['account']}/transactions", None),
        ("GET", "/export/analysis.zip", None),
    ]:
        response = client.request(method, f"{BASE_URL}{path}", json=body, headers=child)
        assert response.status_code == 403, path
        assert response.json()["code"] == "read_only_child", path
    assert client.get(f"{BASE_URL}/me", headers=child).json()["username"] == "Kim"


def test_parent_and_allowance_child_403(client, kim):
    teen = register(client, "teen", role="CHILD")
    assert costs(client, kim["mum"]).status_code == 403
    assert costs(client, teen).status_code == 403


def test_bad_month_422(client, kim):
    for bad in ("2026-13", "March", "2026-3-1"):
        assert costs(client, kim["headers"], bad).status_code == 422, bad
