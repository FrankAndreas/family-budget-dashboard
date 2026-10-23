"""Budgets and Analytics count a receipt's items, not the whole booking (issue #56).

An item counts once in its category and in the totals, and in full under each of its tags."""

from datetime import date

import pytest

from app import reports
from helpers import BASE_URL, admin_headers, category_id, create_account, register, user_id

TODAY = date(2026, 10, 15)
WHEN = "2026-10-10T12:00:00Z"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(reports, "today", lambda: TODAY)


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    admin = admin_headers(client)
    tags = {n: client.post(f"{BASE_URL}/tags", json={"name": n}, headers=admin).json()["id"] for n in ("Velo", "Sport")}
    return {"headers": headers, "account": create_account(client, headers), "tags": tags}


def receipt(client, who, items):
    response = client.post(
        f"{BASE_URL}/transactions",
        json={"account_id": who["account"], "date": WHEN, "items": items},
        headers=who["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def item(client, name, amount, category, **extra):
    return {"name": name, "amount": amount, "category_id": category_id(client, category), **extra}


def summary(client, who, period="month"):
    return client.get(f"{BASE_URL}/reports/summary", params={"range": period}, headers=who["headers"]).json()


def budget(client, who, limit, period="MONTHLY", **target):
    response = client.post(
        f"{BASE_URL}/budgets", json={"limit": limit, "period": period, **target}, headers=who["headers"]
    )
    return response


def two_tag_receipt(client, mum):
    velo, sport = mum["tags"]["Velo"], mum["tags"]["Sport"]
    return receipt(
        client,
        mum,
        [
            item(client, "Velo-Hose", 80, "Clothing", tag_ids=[velo, sport]),
            item(client, "Brot", 20, "Groceries"),
        ],
    )


def test_item_with_two_tags_counts_in_each_tag_once_in_category_and_total(client, mum):
    two_tag_receipt(client, mum)
    result = summary(client, mum)
    assert result["expenses"] == 100
    assert {c["name"]: c["amount"] for c in result["by_category"]} == {"Clothing": 80, "Groceries": 20}
    assert {t["name"]: t["amount"] for t in result["by_tag"]} == {"Velo": 80, "Sport": 80}


def test_discount_item_lowers_its_category(client, mum):
    receipt(client, mum, [item(client, "Kaffee", 12, "Groceries"), item(client, "Aktion", -2, "Groceries")])
    result = summary(client, mum)
    assert result["expenses"] == 10 and result["by_category"][0]["amount"] == 10


def test_category_budget_counts_items(client, mum):
    two_tag_receipt(client, mum)
    assert budget(client, mum, 200, category_id=category_id(client, "Clothing")).json()["spent"] == 80


def test_tag_budget_counts_items_with_the_tag(client, mum):
    two_tag_receipt(client, mum)
    created = budget(client, mum, 4000, "YEARLY", tag_id=mum["tags"]["Velo"]).json()
    assert created["spent"] == 80 and created["tag_id"] == mum["tags"]["Velo"] and created["category_id"] is None
    listed = client.get(f"{BASE_URL}/budgets", headers=mum["headers"]).json()
    assert listed[0]["spent"] == 80


def test_budget_needs_exactly_one_of_category_or_tag(client, mum):
    assert budget(client, mum, 100).status_code == 422
    both = budget(client, mum, 100, category_id=category_id(client, "Clothing"), tag_id=mum["tags"]["Velo"])
    assert both.status_code == 422
    assert budget(client, mum, 100, tag_id="nope").status_code == 400


def test_by_person(client, mum):
    me = user_id(client, mum["headers"], "mum")
    receipt(client, mum, [item(client, "Hose", 80, "Clothing", person_id=me), item(client, "Brot", 20, "Groceries")])
    assert summary(client, mum)["by_person"] == [{"person_id": me, "name": "mum", "amount": 80}]


def test_child_costs_include_items_for_a_dependent_child(client):
    admin = admin_headers(client)
    client.post(f"{BASE_URL}/members", json={"username": "kid"}, headers=admin)
    kid = user_id(client, admin, "kid")
    who = {"headers": admin, "account": create_account(client, admin)}
    receipt(client, who, [item(client, "Schuhe", 50, "Clothing", person_id=kid), item(client, "Brot", 5, "Groceries")])
    assert summary(client, who)["by_child"] == [{"member_id": kid, "name": "kid", "amount": 50}]
