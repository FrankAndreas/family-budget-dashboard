"""Month check on clearing accounts: each completed month's own bookings add up to 0; the gap is booked once."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from helpers import BASE_URL, add_transaction, balance, category_id, create_account, register, user_id


def clearing(client, headers, name="Migros"):
    return client.post(f"{BASE_URL}/accounts", json={"name": name, "type": "CLEARING"}, headers=headers).json()["id"]


class TestSetup:
    def test_unknown_expense_seeded(self, client):
        types = {c["name"]: c["type"] for c in client.get(f"{BASE_URL}/categories").json()}
        assert types["Unknown expense"] == "EXPENSE"

    def test_clearing_account_created_and_switched(self, client):
        headers = register(client, "mum")
        bank = create_account(client, headers, "Migros")
        assert client.put(f"{BASE_URL}/accounts/{bank}", json={"type": "CLEARING"}, headers=headers).status_code == 200
        created = clearing(client, headers, "Card")
        types = {a["id"]: a["type"] for a in client.get(f"{BASE_URL}/accounts", headers=headers).json()}
        assert types[bank] == "CLEARING" and types[created] == "CLEARING"


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    return {"headers": headers, "migros": clearing(client, headers)}


def put(client, mum, category, amount, date):
    response = add_transaction(client, mum["headers"], mum["migros"], category_id(client, category), amount, date=date)
    assert response.status_code == 200, response.text
    return response.json()


def check(client, headers, account):
    return client.get(f"{BASE_URL}/accounts/{account}/month-check", headers=headers)


def book(client, headers, account, month):
    return client.post(f"{BASE_URL}/accounts/{account}/month-check/{month}", headers=headers)


class TestList:
    def test_each_month_on_its_own_bookings(self, client, mum):
        put(client, mum, "Gift", 300, "2025-08-03")
        put(client, mum, "Groceries", 250, "2025-08-04")
        put(client, mum, "Gift", 100, "2025-09-03")
        put(client, mum, "Groceries", 100, "2025-09-04")
        assert check(client, mum["headers"], mum["migros"]).json() == [
            {"month": "2025-08", "money_in": 300.0, "money_out": 250.0, "difference": 50.0, "booked": False}
        ]

    def test_newest_first_both_signs(self, client, mum):
        put(client, mum, "Gift", 10, "2025-07-03")
        put(client, mum, "Gift", 100, "2025-08-03")
        put(client, mum, "Groceries", 112.40, "2025-08-04")
        rows = check(client, mum["headers"], mum["migros"]).json()
        assert [(r["month"], r["difference"]) for r in rows] == [("2025-08", -12.4), ("2025-07", 10.0)]

    def test_swiss_month_boundaries(self, client, mum):
        put(client, mum, "Gift", 50, "2025-08-31T21:30:00Z")  # 23:30 in Zurich: August
        put(client, mum, "Groceries", 50, "2025-08-15")
        put(client, mum, "Gift", 20, "2025-08-31T22:30:00Z")  # 00:30 on 1 September in Zurich
        put(client, mum, "Groceries", 20, "2025-09-10")
        assert check(client, mum["headers"], mum["migros"]).json() == []

    def test_cents_add_up(self, client, mum):
        put(client, mum, "Gift", 0.1, "2025-08-01")
        put(client, mum, "Gift", 0.2, "2025-08-01")
        put(client, mum, "Groceries", 0.3, "2025-08-02")
        assert check(client, mum["headers"], mum["migros"]).json() == []

    def test_current_month_left_out(self, client, mum):
        put(client, mum, "Gift", 20, datetime.now(ZoneInfo("Europe/Zurich")).isoformat())
        assert check(client, mum["headers"], mum["migros"]).json() == []

    def test_only_clearing_accounts(self, client, mum):
        bank = create_account(client, mum["headers"], "Bank")
        response = check(client, mum["headers"], bank)
        assert response.status_code == 400
        assert response.json()["detail"] == "Only clearing accounts have a month check"

    def test_view_share_sees_but_cannot_book(self, client, mum):
        dad = register(client, "dad")
        dads = clearing(client, dad)
        add_transaction(client, dad, dads, category_id(client, "Gift"), 5, date="2025-08-01")
        client.put(f"{BASE_URL}/shares/{user_id(client, dad, 'mum')}", json={"level": "VIEW"}, headers=dad)
        assert check(client, mum["headers"], dads).status_code == 200
        assert book(client, mum["headers"], dads, "2025-08").status_code == 403


class TestBook:
    def test_gap_booked_as_unknown_expense(self, client, mum):
        put(client, mum, "Gift", 300, "2025-08-03")
        put(client, mum, "Groceries", 250, "2025-08-04")
        response = book(client, mum["headers"], mum["migros"], "2025-08")
        assert response.status_code == 200, response.text
        booked = response.json()
        assert booked["category_id"] == category_id(client, "Unknown expense")
        assert booked["amount"] == -50.0
        assert booked["description"] == "Month check August 2025"
        assert booked["reference"] == "month-check:2025-08"
        assert booked["date"].startswith("2025-08-31T12:00")
        assert check(client, mum["headers"], mum["migros"]).json() == []
        assert balance(client, mum["headers"], mum["migros"]) == 0

    def test_receipts_over_booked_as_income(self, client, mum):
        put(client, mum, "Gift", 100, "2025-08-03")
        put(client, mum, "Groceries", 112.40, "2025-08-04")
        booked = book(client, mum["headers"], mum["migros"], "2025-08").json()
        assert booked["category_id"] == category_id(client, "Other Income")
        assert booked["amount"] == 12.4

    def test_booked_once_until_deleted(self, client, mum):
        put(client, mum, "Gift", 300, "2025-08-03")
        put(client, mum, "Groceries", 250, "2025-08-04")
        first = book(client, mum["headers"], mum["migros"], "2025-08").json()
        put(client, mum, "Groceries", 5, "2025-08-05")  # a receipt that turned up later
        assert check(client, mum["headers"], mum["migros"]).json()[0]["booked"] is True
        second = book(client, mum["headers"], mum["migros"], "2025-08")
        assert second.status_code == 409
        client.delete(f"{BASE_URL}/transactions/{first['id']}", headers=mum["headers"])
        assert book(client, mum["headers"], mum["migros"], "2025-08").json()["amount"] == -45.0

    @pytest.mark.parametrize(
        "month, detail",
        [
            ("2025-13", "Month must be YYYY-MM"),
            ("2025-07", "This month adds up already"),
            (datetime.now(ZoneInfo("Europe/Zurich")).strftime("%Y-%m"), "Only completed months can be checked"),
            ("2999-01", "Only completed months can be checked"),
        ],
    )
    def test_errors(self, client, mum, month, detail):
        response = book(client, mum["headers"], mum["migros"], month)
        assert response.status_code == 400
        assert response.json()["detail"] == detail
