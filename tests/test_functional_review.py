"""Findings of the functional review (2026-11-07): bookings dated later count when their month comes, refunds lower
their expense category everywhere spending is added up, and generated texts follow the person's language."""

from datetime import date

import pytest

from app import reports
from helpers import (
    BASE_URL,
    add_member,
    add_transaction,
    balance,
    balance_of,
    category_id,
    create_account,
    create_split,
    register,
    set_language,
    user_id,
)
from test_import_rules import csv, rows, send

TODAY = date(2026, 10, 15)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(reports, "today", lambda: TODAY)


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    return {
        "headers": headers,
        "account": create_account(client, headers, "Bank"),
        "id": user_id(client, headers, "mum"),
    }


def book(client, who, category, amount, when, **extra):
    response = add_transaction(
        client, who["headers"], who["account"], category_id(client, category), amount, date=when, **extra
    )
    assert response.status_code == 200, response.text
    return response.json()


def summary(client, who, period="month"):
    response = client.get(f"{BASE_URL}/reports/summary", params={"range": period}, headers=who["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def budget(client, who, category, limit=500, period="MONTHLY"):
    body = {"category_id": category_id(client, category), "limit": limit, "period": period}
    assert client.post(f"{BASE_URL}/budgets", json=body, headers=who["headers"]).status_code == 200


def spent(client, who):
    return [b["spent"] for b in client.get(f"{BASE_URL}/budgets", headers=who["headers"]).json()]


class TestFutureBookings:
    """A booking dated later (typed in ahead, imported with a future date) counts when its month comes."""

    def test_next_month_not_in_this_month(self, client, mum):
        book(client, mum, "Groceries", 40, "2026-10-10T12:00:00Z")
        book(client, mum, "Groceries", 100, "2026-11-03T12:00:00Z")
        budget(client, mum, "Groceries")
        data = summary(client, mum)
        assert data["expenses"] == 40.0
        assert [c["amount"] for c in data["by_category"]] == [40.0]
        assert spent(client, mum) == [40.0]
        # The totals match the charts, which end with this month
        assert data["expenses"] == data["months"][-1]["expenses"] == sum(d["expenses"] for d in data["days"])

    def test_year_ends_with_the_year(self, client, mum):
        book(client, mum, "Groceries", 100, "2026-11-03T12:00:00Z")
        book(client, mum, "Groceries", 7, "2027-01-05T12:00:00Z")
        budget(client, mum, "Groceries", period="YEARLY")
        assert summary(client, mum, "year")["expenses"] == 100.0
        assert spent(client, mum) == [100.0]
        # "All" has no end
        assert summary(client, mum, "all")["expenses"] == 107.0


class TestRefunds:
    """Money back in an expense category (the jacket returned) lowers that category's spending."""

    def test_lowers_the_category_everywhere(self, client, mum):
        book(client, mum, "Salary", 1000, "2026-10-01T12:00:00Z")
        book(client, mum, "Clothing", 200, "2026-10-05T12:00:00Z")
        refund = book(client, mum, "Clothing", 80, "2026-10-08T12:00:00Z", refund=True)
        assert refund["amount"] == 80.0
        budget(client, mum, "Clothing")
        data = summary(client, mum)
        assert (data["income"], data["expenses"]) == (1000.0, 120.0)
        assert [(c["name"], c["amount"]) for c in data["by_category"]] == [("Clothing", 120.0)]
        assert spent(client, mum) == [120.0]
        assert balance(client, mum["headers"], mum["account"]) == 880.0

    def test_stays_a_refund_when_edited(self, client, mum):
        refund = book(client, mum, "Clothing", 80, "2026-10-08T12:00:00Z", refund=True)
        url = f"{BASE_URL}/transactions/{refund['id']}"
        changed = client.put(url, json={"amount": 50, "description": "Retoure"}, headers=mum["headers"]).json()
        assert changed["amount"] == 50.0
        # Turned into an expense on purpose
        assert client.put(url, json={"refund": False}, headers=mum["headers"]).json()["amount"] == -50.0

    def test_ignored_for_income(self, client, mum):
        assert book(client, mum, "Salary", 100, "2026-10-01T12:00:00Z", refund=True)["amount"] == 100.0

    def test_shared_refund_lowers_what_the_others_owe(self, client, mum):
        register(client, "dad")
        ids = {n: user_id(client, mum["headers"], n) for n in ("mum", "dad", "Admin")}
        split = create_split(client, mum["headers"], "Halb", {ids["mum"]: 50, ids["dad"]: 50, ids["Admin"]: 0}).json()
        book(client, mum, "Groceries", 100, "2026-10-05T12:00:00Z", split_id=split["id"])
        book(client, mum, "Groceries", 20, "2026-10-06T12:00:00Z", split_id=split["id"], refund=True)
        assert balance_of(client, mum["headers"], ids["dad"]) == -40.0

    def test_lowers_a_childs_costs(self, client, mum):
        lina = add_member(client, "lina")
        book(client, mum, "Clothing", 60, "2026-10-05T12:00:00Z", member_id=lina)
        book(client, mum, "Clothing", 15, "2026-10-09T12:00:00Z", member_id=lina, refund=True)
        assert [c["amount"] for c in summary(client, mum)["by_child"]] == [45.0]

    def test_cant_be_a_purchase(self, client, mum):
        asset = client.post(
            f"{BASE_URL}/assets",
            json={
                "name": "Velo",
                "price": 900,
                "purchase_date": "2026-01-01",
                "lifespan_years": 5,
                "owner_id": mum["id"],
            },
            headers=mum["headers"],
        ).json()
        response = add_transaction(
            client,
            mum["headers"],
            mum["account"],
            category_id(client, "Transportation"),
            50,
            asset_id=asset["id"],
            asset_purchase=True,
            refund=True,
        )
        assert response.status_code == 400

    def test_imported_with_direction_in(self, client, mum):
        lines = csv(
            "2026-10-07,Bank,Clothing,80,in,Retoure Muster,ref:1", "2026-10-05,Bank,Clothing,200,out,Jacke,ref:2"
        )
        response = send(client, mum["headers"], lines, path="import")
        assert response.status_code == 200, response.text
        assert summary(client, mum)["expenses"] == 120.0

    def test_credit_changed_to_an_expense_category_in_the_preview(self, client, mum):
        credit = "2026-10-07,Bank,Other Income,80,,Retoure Muster,ref:3"
        [row] = rows(client, mum["headers"], csv(credit), {"2": {"category": "Clothing"}})
        assert (row["status"], row["category"], row["direction"]) == ("ok", "Clothing", "in")
        assert (
            send(
                client, mum["headers"], csv(credit), changes={"2": {"category": "Clothing"}}, path="import"
            ).status_code
            == 200
        )
        assert summary(client, mum)["by_category"] == [
            {"category_id": category_id(client, "Clothing"), "name": "Clothing", "amount": -80.0}
        ]

    def test_rules_never_turn_a_credit_into_a_refund(self, client, mum):
        rule = {"text": "Muster", "category_id": category_id(client, "Clothing")}
        assert client.post(f"{BASE_URL}/import/rules", json=rule, headers=mum["headers"]).status_code == 200
        [row] = rows(client, mum["headers"], csv("2026-10-07,Bank,Other Income,80,,TWINT Muster,ref:4"))
        assert row["category"] == "Other Income"


class TestTexts:
    def test_month_check_and_settle_up_in_german(self, client, mum):
        set_language(mum["headers"], "de")
        migros = client.post(
            f"{BASE_URL}/accounts", json={"name": "Migros", "type": "CLEARING"}, headers=mum["headers"]
        ).json()
        add_transaction(
            client, mum["headers"], migros["id"], category_id(client, "Groceries"), 30, date="2026-03-10T12:00:00Z"
        )
        booked = client.post(f"{BASE_URL}/accounts/{migros['id']}/month-check/2026-03", headers=mum["headers"])
        assert booked.status_code == 200, booked.text
        assert booked.json()["description"] == "Monatskontrolle März 2026"

        dad = register(client, "dad")
        dad_account = create_account(client, dad, "Dad")
        settled = client.post(
            f"{BASE_URL}/settlements",
            json={
                "from_user_id": mum["id"],
                "to_user_id": user_id(client, dad, "dad"),
                "amount": 10,
                "from_account_id": mum["account"],
                "to_account_id": dad_account,
            },
            headers=mum["headers"],
        )
        assert settled.status_code == 200, settled.text
        descriptions = {
            t["description"]
            for t in client.get(f"{BASE_URL}/accounts/{mum['account']}/transactions", headers=mum["headers"]).json()
        }
        assert "Ausgleich" in descriptions
