"""The booking that bought an investment, and investments' tags in Analytics: spent, and set aside apart from it."""

from datetime import date

import pytest

from app import common_api, reports
from helpers import BASE_URL, add_transaction, category_id, create_account, create_split, register, user_id

WHEN = "2026-10-10T12:00:00Z"


@pytest.fixture
def family(client, monkeypatch):
    monkeypatch.setattr(common_api, "today", lambda: date(2026, 10, 15))
    monkeypatch.setattr(reports, "today", lambda: date(2026, 10, 15))
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/users/{user_id(client, mum, 'Admin')}", json={"is_active": False}, headers=mum)
    mum_id, dad_id = user_id(client, mum, "mum"), user_id(client, mum, "dad")
    split = create_split(client, mum, "Equal", {mum_id: 50, dad_id: 50}).json()["id"]
    mobility = client.post(f"{BASE_URL}/tags", json={"name": "Mobilität"}, headers=mum).json()["id"]
    car = client.post(
        f"{BASE_URL}/assets",
        json={
            "name": "Auto",
            "price": 28000,
            "purchase_date": "2026-09-01",
            "lifespan_years": 8,
            "split_id": split,
            "tag_id": mobility,
        },
        headers=mum,
    ).json()
    return {
        "mum": mum,
        "dad": dad,
        "mum_id": mum_id,
        "account": create_account(client, mum, "Mum bank"),
        "car": car,
        "mobility": mobility,
    }


def asset(client, family):
    return client.get(f"{BASE_URL}/assets/{family['car']['id']}", headers=family["mum"]).json()


def book(client, family, amount, **extra):
    response = add_transaction(
        client, family["mum"], family["account"], category_id(client, "Transportation"), amount, date=WHEN, **extra
    )
    assert response.status_code == 200, response.text
    return response.json()


def by_tag(client, headers):
    rows = client.get(f"{BASE_URL}/reports/summary", params={"range": "month"}, headers=headers).json()["by_tag"]
    return {row["name"]: (row["amount"], row["set_aside"]) for row in rows}


def test_purchase_fills_price_and_date_and_is_no_follow_up(client, family):
    assert family["car"]["purchase"] is None
    paid = book(client, family, 30000, asset_id=family["car"]["id"], asset_purchase=True)
    assert paid["asset_purchase"] is True
    car = asset(client, family)
    assert (car["price"], car["purchase_date"]) == (30000, "2026-10-10")
    assert car["purchase"]["transaction_id"] == paid["id"] and car["purchase"]["amount"] == 30000
    book(client, family, 600, asset_id=family["car"]["id"])
    car = asset(client, family)
    assert car["total_cost"] == 30600
    assert [e["amount"] for e in car["expenses"]] == [-600]

    # Changed by hand afterwards (a trade-in): saving the booking again keeps it
    body = {
        "name": "Auto",
        "price": 26000,
        "purchase_date": "2026-10-10",
        "lifespan_years": 8,
        "split_id": car["split_id"],
        "tag_id": family["mobility"],
    }
    client.put(f"{BASE_URL}/assets/{car['id']}", json=body, headers=family["mum"])
    client.put(
        f"{BASE_URL}/transactions/{paid['id']}",
        json={"description": "Garage", "asset_purchase": True},
        headers=family["mum"],
    )
    assert asset(client, family)["price"] == 26000


def test_one_purchase_per_investment(client, family):
    first = book(client, family, 10000, asset_id=family["car"]["id"], asset_purchase=True)
    second = book(client, family, 20000, asset_id=family["car"]["id"], asset_purchase=True)
    assert asset(client, family)["purchase"]["transaction_id"] == second["id"]
    transactions = client.get(f"{BASE_URL}/accounts/{family['account']}/transactions", headers=family["mum"]).json()
    assert {t["id"]: t["asset_purchase"] for t in transactions} == {first["id"]: False, second["id"]: True}
    # The first one is a follow-up now
    assert asset(client, family)["total_cost"] == 30000

    # Unlinked: no purchase any more; price and date stay
    client.put(f"{BASE_URL}/transactions/{second['id']}", json={"asset_id": None}, headers=family["mum"])
    car = asset(client, family)
    assert car["purchase"] is None and car["price"] == 20000


def test_purchase_needs_an_investment(client, family):
    response = add_transaction(
        client, family["mum"], family["account"], category_id(client, "Transportation"), 5, asset_purchase=True
    )
    assert response.status_code == 400


def test_receipt_as_the_purchase_shows_its_attachments(client, family):
    pdf = client.post(
        f"{BASE_URL}/attachments",
        files={"file": ("garantie.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers=family["mum"],
    ).json()
    response = client.post(
        f"{BASE_URL}/transactions",
        json={
            "account_id": family["account"],
            "date": WHEN,
            "asset_id": family["car"]["id"],
            "asset_purchase": True,
            "attachment_ids": [pdf["id"]],
            "items": [{"name": "Auto", "amount": 30000, "category_id": category_id(client, "Transportation")}],
        },
        headers=family["mum"],
    )
    assert response.status_code == 200, response.text
    purchase = asset(client, family)["purchase"]
    assert [a["filename"] for a in purchase["attachments"]] == ["garantie.pdf"]


def test_analytics_spent_and_set_aside_per_tag(client, family):
    book(client, family, 30000, asset_id=family["car"]["id"], asset_purchase=True)
    book(client, family, 600, asset_id=family["car"]["id"])
    # A receipt linked to the car: its items count under the car's tag, an item with that tag only once
    client.post(
        f"{BASE_URL}/transactions",
        json={
            "account_id": family["account"],
            "date": WHEN,
            "asset_id": family["car"]["id"],
            "items": [
                {
                    "name": "Reifen",
                    "amount": 400,
                    "category_id": category_id(client, "Transportation"),
                    "tag_ids": [family["mobility"]],
                },
                {"name": "Wischer", "amount": 40, "category_id": category_id(client, "Transportation")},
            ],
        },
        headers=family["mum"],
    )
    # 30000 over 8 years = 312.50 a month, half each
    assert by_tag(client, family["mum"]) == {"Mobilität": (31040, 156.25)}
    # Dad paid nothing but sets aside his half
    assert by_tag(client, family["dad"]) == {"Mobilität": (0, 156.25)}

    budget = client.post(
        f"{BASE_URL}/budgets",
        json={"limit": 40000, "period": "MONTHLY", "tag_id": family["mobility"]},
        headers=family["mum"],
    ).json()
    assert budget["spent"] == 31040

    client.post(
        f"{BASE_URL}/assets/{family['car']['id']}/archive", json={"archived_on": "2026-10-15"}, headers=family["mum"]
    )
    assert by_tag(client, family["dad"]) == {}


def test_lease_sets_aside_the_buy_out_only(client, family):
    before = by_tag(client, family["mum"])["Mobilität"][1]
    client.post(
        f"{BASE_URL}/assets",
        json={
            "name": "Leasing",
            "kind": "LEASE",
            "price": 5000,
            "purchase_date": "2026-03-01",
            "lifespan_years": 10,
            "lease_rate": 390,
            "lease_months": 48,
            "lease_final": 12000,
            "owner_id": family["mum_id"],
            "tag_id": family["mobility"],
        },
        headers=family["mum"],
    )
    # The rates are booked (spent); set aside on top of the common car's half: the buy-out over the term
    assert by_tag(client, family["mum"]) == {"Mobilität": (0, round(before + 250, 2))}
