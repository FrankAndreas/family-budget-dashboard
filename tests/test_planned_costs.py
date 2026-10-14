"""Yearly bills and common monthly costs, with set-asides and each parent's monthly share."""

from datetime import date

import pytest

from app import common_api
from helpers import BASE_URL, category_id, create_split, register, user_id


@pytest.fixture
def parents(client, monkeypatch):
    monkeypatch.setattr(common_api, "today", lambda: date(2026, 11, 20))
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/users/{user_id(client, mum, 'Admin')}", json={"is_active": False}, headers=mum)
    mum_id, dad_id = user_id(client, mum, "mum"), user_id(client, mum, "dad")
    split = create_split(client, mum, "By income", {mum_id: 70, dad_id: 30}).json()["id"]
    return {"mum": mum, "dad": dad, "mum_id": mum_id, "dad_id": dad_id, "split": split}


def add_cost(client, headers, **fields):
    body = {
        "name": "Insurance",
        "category_id": category_id(client, "Healthcare"),
        "amount": 1200,
        "frequency": "YEARLY",
        "due_month": 1,
    }
    return client.post(f"{BASE_URL}/planned-costs", json=body | fields, headers=headers)


def test_common_yearly_bill(client, parents):
    assert add_cost(client, parents["mum"], split_id=parents["split"]).status_code == 200
    bill = client.get(f"{BASE_URL}/planned-costs", params={"frequency": "YEARLY"}, headers=parents["dad"]).json()[0]
    assert bill["monthly"] == 100
    assert bill["next_due"] == "2027-01-01" and bill["due_soon"] is True
    assert bill["shares"] == {parents["mum_id"]: 70.0, parents["dad_id"]: 30.0}


def test_personal_bill_private_unless_shared(client, parents):
    add_cost(client, parents["mum"], owner_id=parents["mum_id"], name="Phone", due_month=6)
    assert client.get(f"{BASE_URL}/planned-costs", headers=parents["dad"]).json() == []
    client.put(f"{BASE_URL}/shares/{parents['dad_id']}", json={"level": "VIEW"}, headers=parents["mum"])
    bills = client.get(f"{BASE_URL}/planned-costs", headers=parents["dad"]).json()
    assert [b["name"] for b in bills] == ["Phone"]
    assert bills[0]["due_soon"] is False
    assert client.delete(f"{BASE_URL}/planned-costs/{bills[0]['id']}", headers=parents["dad"]).status_code == 404


def test_planned_cost_validation(client, parents):
    mum = parents["mum"]
    assert add_cost(client, mum).status_code == 400  # neither owner nor split
    assert add_cost(client, mum, owner_id=parents["mum_id"], split_id=parents["split"]).status_code == 400
    assert add_cost(client, mum, owner_id=parents["mum_id"], due_month=None).status_code == 400
    assert add_cost(client, mum, owner_id=parents["mum_id"], frequency="MONTHLY", due_month=None).status_code == 400
    assert add_cost(client, mum, owner_id=parents["dad_id"]).status_code == 403
    assert add_cost(client, mum, owner_id=parents["mum_id"], due_month=13).status_code == 422
    assert add_cost(client, mum, owner_id=parents["mum_id"], amount=-5).status_code == 422
    teen = register(client, "teen", role="CHILD", by=mum)
    assert client.get(f"{BASE_URL}/planned-costs", headers=teen).status_code == 403
    # A younger child's bills are managed by the parents
    timmy = client.post(f"{BASE_URL}/members", json={"username": "timmy"}, headers=mum).json()
    assert add_cost(client, parents["dad"], owner_id=timmy["id"], name="Football club").status_code == 200


def test_monthly_overview(client, parents):
    mum, split = parents["mum"], parents["split"]
    add_cost(client, mum, split_id=split)  # 1200 a year -> 100 a month
    add_cost(client, mum, name="Rent", frequency="MONTHLY", due_month=None, amount=2000, split_id=split)
    add_cost(client, mum, name="Phone", owner_id=parents["mum_id"])  # personal: not in the common overview
    overview = client.get(f"{BASE_URL}/common/overview", headers=parents["dad"]).json()
    assert sorted(item["name"] for item in overview["items"]) == ["Insurance", "Rent"]
    assert overview["totals"] == {parents["mum_id"]: 1470.0, parents["dad_id"]: 630.0}


def test_edit_and_split_in_use(client, parents):
    bill = add_cost(client, parents["mum"], split_id=parents["split"]).json()
    edited = client.put(f"{BASE_URL}/planned-costs/{bill['id']}", json={**bill, "amount": 600}, headers=parents["dad"])
    assert edited.status_code == 200 and edited.json()["monthly"] == 50
    assert client.delete(f"{BASE_URL}/splits/{parents['split']}", headers=parents["mum"]).status_code == 409
    assert client.delete(f"{BASE_URL}/planned-costs/{bill['id']}", headers=parents["dad"]).status_code == 200
    assert client.delete(f"{BASE_URL}/splits/{parents['split']}", headers=parents["mum"]).status_code == 200
