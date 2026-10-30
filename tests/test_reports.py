"""Budgets and analytics calculated on the server, in Swiss time (issue #30)."""

from datetime import date

import pytest

from app import reports
from helpers import add_member, BASE_URL, add_transaction, category_id, create_account, register, user_id

TODAY = date(2026, 10, 15)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(reports, "today", lambda: TODAY)


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    return {"headers": headers, "account": create_account(client, headers), "id": user_id(client, headers, "mum")}


def book(client, who, category, amount, when, **extra):
    response = add_transaction(
        client, who["headers"], who["account"], category_id(client, category), amount, date=when, **extra
    )
    assert response.status_code == 200, response.text
    return response.json()


def summary(client, who, period="month", **params):
    response = client.get(f"{BASE_URL}/reports/summary", params={"range": period, **params}, headers=who["headers"])
    assert response.status_code == 200, response.text
    return response.json()


class TestSummary:
    def test_totals_and_categories(self, client, mum):
        book(client, mum, "Salary", 5000, "2026-10-01")
        book(client, mum, "Groceries", 80.5, "2026-10-03")
        book(client, mum, "Groceries", 20, "2026-10-04")
        book(client, mum, "Healthcare", 150, "2026-10-05")
        data = summary(client, mum)
        assert (data["income"], data["expenses"]) == (5000.0, 250.5)
        assert [(c["name"], c["amount"]) for c in data["by_category"]] == [("Healthcare", 150.0), ("Groceries", 100.5)]

    def test_transfers_never_count(self, client, mum):
        from test_import import csv_file, upload

        lines = csv_file(
            "2026-10-02,Bank,Transfer,300,out,Savings,,",
            header="date,account,category,amount,direction,description,for,item",
        )
        assert upload(client, mum["headers"], lines, path="import").status_code == 200
        data = summary(client, mum)
        assert (data["income"], data["expenses"], data["by_category"]) == (0.0, 0.0, [])

    @pytest.mark.parametrize(
        "period, expected",
        [("month", 10.0), ("3months", 10.0 + 20.0), ("year", 10.0 + 20.0 + 40.0), ("all", 10.0 + 20.0 + 40.0 + 80.0)],
    )
    def test_ranges(self, client, mum, period, expected):
        book(client, mum, "Groceries", 10, "2026-10-01")
        book(client, mum, "Groceries", 20, "2026-08-01")
        book(client, mum, "Groceries", 40, "2026-01-01")
        book(client, mum, "Groceries", 80, "2025-12-31")
        assert summary(client, mum, period)["expenses"] == expected

    def test_swiss_days_and_months(self, client, mum):
        book(client, mum, "Groceries", 7, "2026-09-30T21:30:00Z")  # 23:30 on 30 September in Zurich
        book(client, mum, "Groceries", 3, "2026-09-30T22:30:00Z")  # 00:30 on 1 October in Zurich
        data = summary(client, mum)
        assert data["expenses"] == 3.0
        assert data["days"][0] == {"date": "2026-10-01", "income": 0.0, "expenses": 3.0}
        assert len(data["days"]) == 31
        months = {m["month"]: m["expenses"] for m in data["months"]}
        assert list(months) == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
        assert (months["2026-09"], months["2026-10"]) == (7.0, 3.0)

    def test_months_across_new_year(self, client, mum, monkeypatch):
        monkeypatch.setattr(reports, "today", lambda: date(2027, 2, 10))
        assert [m["month"] for m in summary(client, mum)["months"]] == [
            "2026-09",
            "2026-10",
            "2026-11",
            "2026-12",
            "2027-01",
            "2027-02",
        ]
        book(client, mum, "Groceries", 5, "2026-12-15")
        assert summary(client, mum, "3months")["expenses"] == 5.0

    def test_children(self, client, mum):
        add_member(client, "Kim")
        kim = user_id(client, mum["headers"], "Kim")
        book(client, mum, "Clothing", 60, "2026-10-02", member_id=kim)
        book(client, mum, "Clothing", 40, "2026-10-02")
        assert summary(client, mum)["by_child"] == [{"member_id": kim, "name": "Kim", "amount": 60.0}]

    def test_access(self, client, mum):
        dad = register(client, "dad")
        response = client.get(f"{BASE_URL}/reports/summary", params={"user_id": mum["id"]}, headers=dad)
        assert response.status_code == 403
        client.put(f"{BASE_URL}/shares/{user_id(client, dad, 'dad')}", json={"level": "VIEW"}, headers=mum["headers"])
        book(client, mum, "Groceries", 12, "2026-10-02")
        response = client.get(f"{BASE_URL}/reports/summary", params={"user_id": mum["id"]}, headers=dad)
        assert response.json()["expenses"] == 12.0
        assert client.get(f"{BASE_URL}/reports/summary", params={"range": "week"}, headers=dad).status_code == 422


class TestBudgets:
    def budget(self, client, who, category, limit, period="MONTHLY"):
        body = {"category_id": category_id(client, category), "limit": limit, "period": period}
        response = client.post(f"{BASE_URL}/budgets", json=body, headers=who["headers"])
        assert response.status_code == 200, response.text
        return response.json()

    def test_spent_this_month_and_year(self, client, mum):
        book(client, mum, "Groceries", 30, "2026-10-02")
        book(client, mum, "Groceries", 50, "2026-03-02")
        book(client, mum, "Healthcare", 99, "2026-10-02")
        monthly = self.budget(client, mum, "Groceries", 200)
        assert (monthly["spent"], monthly["percentage"]) == (30.0, 15.0)
        self.budget(client, mum, "Clothing", 1000, "YEARLY")
        listed = {b["period"]: b for b in client.get(f"{BASE_URL}/budgets", headers=mum["headers"]).json()}
        assert listed["MONTHLY"]["spent"] == 30.0
        assert listed["YEARLY"]["spent"] == 0.0

    def test_yearly(self, client, mum):
        book(client, mum, "Groceries", 30, "2026-10-02")
        book(client, mum, "Groceries", 50, "2026-03-02")
        book(client, mum, "Groceries", 70, "2025-12-02")
        yearly = self.budget(client, mum, "Groceries", 300, "YEARLY")
        assert (yearly["spent"], yearly["percentage"]) == (80.0, 26.7)

    def test_only_the_owners_accounts(self, client, mum):
        dad = {"headers": register(client, "dad")}
        dad["account"] = create_account(client, dad["headers"])
        book(client, dad, "Groceries", 500, "2026-10-02")
        assert self.budget(client, mum, "Groceries", 100)["spent"] == 0.0

    def test_delete_still_works(self, client, mum):
        budget = self.budget(client, mum, "Groceries", 100)
        assert client.delete(f"{BASE_URL}/budgets/{budget['id']}", headers=mum["headers"]).status_code == 200
