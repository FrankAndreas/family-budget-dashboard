"""Investments: replacement planning, inventory notes and total cost of ownership."""

from datetime import date

import pytest

from app import common_api
from helpers import BASE_URL, add_transaction, category_id, create_account, create_split, register, user_id


@pytest.fixture
def parents(client, monkeypatch):
    monkeypatch.setattr(common_api, "today", lambda: date(2026, 10, 14))
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/users/{user_id(client, mum, 'Admin')}", json={"is_active": False}, headers=mum)
    mum_id, dad_id = user_id(client, mum, "mum"), user_id(client, mum, "dad")
    return {
        "mum": mum,
        "dad": dad,
        "mum_id": mum_id,
        "dad_id": dad_id,
        "split": create_split(client, mum, "Equal", {mum_id: 50, dad_id: 50}).json()["id"],
        "mum_account": create_account(client, mum, "Mum bank"),
    }


def add_asset(client, headers, **fields):
    body = {"name": "Car", "price": 24000, "purchase_date": "2022-10-14", "lifespan_years": 8}
    return client.post(f"{BASE_URL}/assets", json=body | fields, headers=headers)


def remove_member(client, headers, member_id, items=None):
    body = {"items": items} if items is not None else None
    return client.request("DELETE", f"{BASE_URL}/users/{member_id}", json=body, headers=headers)


def test_common_asset_with_follow_up_costs(client, parents):
    car = add_asset(client, parents["mum"], split_id=parents["split"], notes="Warranty until 2027").json()
    assert car["monthly_set_aside"] == 250 and car["age_years"] == 4.0
    assert car["replacement_due"] == "2030-10-14" and car["is_due"] is False
    transport = category_id(client, "Transportation")
    service = add_transaction(client, parents["mum"], parents["mum_account"], transport, 600, asset_id=car["id"])
    assert service.status_code == 200
    detail = client.get(f"{BASE_URL}/assets/{car['id']}", headers=parents["dad"]).json()
    assert detail["total_cost"] == 24600 and detail["cost_per_year"] == 6150
    assert [e["amount"] for e in detail["expenses"]] == [-600]
    # Dad sees the linked expense on the asset, not Mum's account
    response = client.get(f"{BASE_URL}/accounts/{parents['mum_account']}/transactions", headers=parents["dad"])
    assert response.status_code == 403


def test_asset_in_monthly_overview(client, parents):
    add_asset(client, parents["mum"], split_id=parents["split"])
    add_asset(client, parents["mum"], name="Bike", price=3000, lifespan_years=5, owner_id=parents["mum_id"])
    overview = client.get(f"{BASE_URL}/common/overview", headers=parents["dad"]).json()
    assert [item["name"] for item in overview["items"]] == ["Car"]
    assert overview["totals"] == {parents["mum_id"]: 125.0, parents["dad_id"]: 125.0}


def test_personal_asset_visibility_and_validation(client, parents):
    bike = add_asset(client, parents["mum"], name="Bike", owner_id=parents["mum_id"]).json()
    assert client.get(f"{BASE_URL}/assets", headers=parents["dad"]).json() == []
    assert client.get(f"{BASE_URL}/assets/{bike['id']}", headers=parents["dad"]).status_code == 404
    assert add_asset(client, parents["mum"], lifespan_years=0, owner_id=parents["mum_id"]).status_code == 422
    assert add_asset(client, parents["mum"]).status_code == 400
    # Linking to an investment you can't see is refused
    transport = category_id(client, "Transportation")
    dad_account = create_account(client, parents["dad"], "Dad bank")
    assert add_transaction(client, parents["dad"], dad_account, transport, 10, asset_id=bike["id"]).status_code == 400


def test_child_owns_an_asset(client, parents):
    teen = register(client, "teen", role="CHILD", by=parents["mum"])
    teen_id = user_id(client, parents["mum"], "teen")
    # Parents only view an allowance child's money by default
    assert add_asset(client, parents["mum"], name="MTB", owner_id=teen_id).status_code == 403
    client.put(f"{BASE_URL}/shares/{parents['mum_id']}", json={"level": "EDIT"}, headers=teen)
    assert add_asset(client, parents["mum"], name="MTB", owner_id=teen_id).status_code == 200
    assert [a["name"] for a in client.get(f"{BASE_URL}/assets", headers=parents["dad"]).json()] == ["MTB"]


def test_deleting_asset_keeps_expenses(client, parents):
    car = add_asset(client, parents["mum"], split_id=parents["split"]).json()
    transport = category_id(client, "Transportation")
    expense = add_transaction(client, parents["mum"], parents["mum_account"], transport, 80, asset_id=car["id"]).json()
    assert client.delete(f"{BASE_URL}/splits/{parents['split']}", headers=parents["mum"]).status_code == 409
    assert client.delete(f"{BASE_URL}/assets/{car['id']}", headers=parents["dad"]).status_code == 200
    kept = client.get(f"{BASE_URL}/accounts/{parents['mum_account']}/transactions", headers=parents["mum"]).json()
    assert [t["id"] for t in kept] == [expense["id"]] and kept[0]["asset_id"] is None


def test_removing_a_member_decides_where_items_go(client, parents):
    mum, dad = parents["mum"], parents["dad"]
    bike = add_asset(client, dad, name="Bike", owner_id=parents["dad_id"]).json()
    tv = add_asset(client, dad, name="TV", owner_id=parents["dad_id"]).json()
    phone = client.post(
        f"{BASE_URL}/planned-costs",
        json={
            "name": "Phone",
            "category_id": category_id(client, "Utilities"),
            "amount": 300,
            "frequency": "YEARLY",
            "due_month": 3,
            "owner_id": parents["dad_id"],
        },
        headers=dad,
    ).json()
    dad_account = create_account(client, dad, "Dad bank")
    add_transaction(client, dad, dad_account, category_id(client, "Groceries"), 40, split_id=parents["split"])
    add_transaction(client, dad, dad_account, category_id(client, "Transportation"), 70, asset_id=bike["id"])
    client.post(
        f"{BASE_URL}/settlements",
        json={
            "from_user_id": parents["mum_id"],
            "to_user_id": parents["dad_id"],
            "amount": 20,
            "from_account_id": parents["mum_account"],
            "to_account_id": dad_account,
        },
        headers=mum,
    )
    client.put(f"{BASE_URL}/shares/{parents['mum_id']}", json={"level": "EDIT"}, headers=dad)

    # The form lists their items, and removing them without a decision is refused
    listed = client.get(f"{BASE_URL}/users/{parents['dad_id']}/items", headers=mum).json()
    assert sorted(item["name"] for item in listed) == ["Bike", "Phone", "TV"]
    refused = remove_member(client, mum, parents["dad_id"])
    assert refused.status_code == 409
    assert len(refused.json()["detail"]["items"]) == 3
    decisions = [
        {"kind": "asset", "id": bike["id"], "to": f"owner:{parents['mum_id']}"},
        {"kind": "asset", "id": tv["id"], "to": "delete"},
        {"kind": "planned", "id": phone["id"], "to": f"split:{parents['split']}"},
    ]
    # Not to the member being removed; nothing changes when a decision is invalid
    bad_target = decisions[:2] + [{"kind": "planned", "id": phone["id"], "to": f"owner:{parents['dad_id']}"}]
    assert remove_member(client, mum, parents["dad_id"], bad_target).status_code == 400
    assert len(client.get(f"{BASE_URL}/users/{parents['dad_id']}/items", headers=mum).json()) == 3
    assert remove_member(client, mum, parents["dad_id"], decisions).status_code == 200

    assets = client.get(f"{BASE_URL}/assets", headers=mum).json()
    assert [(a["name"], a["owner_id"]) for a in assets] == [("Bike", parents["mum_id"])]
    bills = client.get(f"{BASE_URL}/planned-costs", headers=mum).json()
    assert [(b["name"], b["split_id"]) for b in bills] == [("Phone", parents["split"])]
    for path in ("/common/balance", "/common/expenses", "/common/overview", "/settlements", "/splits"):
        assert client.get(f"{BASE_URL}{path}", headers=mum).status_code == 200, path
    assert client.get(f"{BASE_URL}/settlements", headers=mum).json() == []
    # The split no longer names the removed parent
    assert list(client.get(f"{BASE_URL}/splits", headers=mum).json()[0]["shares"]) == [parents["mum_id"]]


def test_removing_member_without_items(client, parents):
    timmy = client.post(f"{BASE_URL}/members", json={"username": "timmy"}, headers=parents["mum"]).json()
    assert client.get(f"{BASE_URL}/users/{timmy['id']}/items", headers=parents["mum"]).json() == []
    assert remove_member(client, parents["mum"], timmy["id"]).status_code == 200
