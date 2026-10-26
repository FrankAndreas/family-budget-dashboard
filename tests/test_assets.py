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


def test_asset_tag(client, parents):
    mobility = client.post(f"{BASE_URL}/tags", json={"name": "Mobilität"}, headers=parents["mum"]).json()
    car = add_asset(client, parents["mum"], split_id=parents["split"], tag_ids=[mobility["id"]]).json()
    assert car["tag_ids"] == [mobility["id"]]
    assert add_asset(client, parents["mum"], split_id=parents["split"], tag_ids=["nope"]).status_code == 400
    # Deleting the tag moves the investment to "no tag"
    assert client.delete(f"{BASE_URL}/tags/{mobility['id']}", headers=parents["mum"]).status_code == 200
    assert client.get(f"{BASE_URL}/assets/{car['id']}", headers=parents["mum"]).json()["tag_ids"] == []


def archive(client, headers, asset_id, on="2026-10-01"):
    return client.post(f"{BASE_URL}/assets/{asset_id}/archive", json={"archived_on": on}, headers=headers)


def test_archived_asset_leaves_the_totals(client, parents):
    car = add_asset(client, parents["mum"], split_id=parents["split"]).json()
    transport = category_id(client, "Transportation")
    linked = add_transaction(client, parents["mum"], parents["mum_account"], transport, 600, asset_id=car["id"]).json()
    response = archive(client, parents["mum"], car["id"])
    assert response.status_code == 200
    archived = response.json()
    assert archived["archived_on"] == "2026-10-01"
    assert (archived["monthly_set_aside"], archived["shares"], archived["is_due"]) == (0, {}, False)
    # Frozen at the archive date: 2022-10-14 → 2026-10-01 is 4.0 years
    assert archived["age_years"] == 4.0 and archived["total_cost"] == 24600
    overview = client.get(f"{BASE_URL}/common/overview", headers=parents["dad"]).json()
    assert overview["items"] == [] and overview["totals"] == {}

    # No new links, but the booking that is linked keeps it when edited
    assert (
        add_transaction(client, parents["mum"], parents["mum_account"], transport, 5, asset_id=car["id"]).status_code
        == 400
    )
    edit = client.put(
        f"{BASE_URL}/transactions/{linked['id']}",
        json={"description": "Service", "asset_id": car["id"]},
        headers=parents["mum"],
    )
    assert edit.status_code == 200 and edit.json()["asset_id"] == car["id"]

    restored = client.delete(f"{BASE_URL}/assets/{car['id']}/archive", headers=parents["mum"]).json()
    assert restored["archived_on"] is None and restored["monthly_set_aside"] == 250


def test_archive_checks(client, parents):
    bike = add_asset(client, parents["mum"], name="Bike", owner_id=parents["mum_id"]).json()
    assert archive(client, parents["dad"], bike["id"]).status_code == 404
    assert archive(client, parents["mum"], bike["id"], on="2022-10-13").status_code == 400
    assert archive(client, parents["mum"], bike["id"], on="2026-10-15").status_code == 400
    # Editing an archived investment keeps it archived
    archive(client, parents["mum"], bike["id"])
    body = {
        "name": "E-Bike",
        "price": 24000,
        "purchase_date": "2022-10-14",
        "lifespan_years": 8,
        "owner_id": parents["mum_id"],
    }
    edited = client.put(f"{BASE_URL}/assets/{bike['id']}", json=body, headers=parents["mum"]).json()
    assert edited["archived_on"] == "2026-10-01"


LEASE = {
    "name": "Leasingauto",
    "kind": "LEASE",
    "price": 5000,
    "purchase_date": "2025-03-01",
    "lifespan_years": 10,
    "lease_rate": 390,
    "lease_months": 48,
    "lease_final": 12000,
}


def test_lease_during_the_term(client, parents):
    car = add_asset(client, parents["mum"], split_id=parents["split"], **LEASE).json()
    # The buy-out is saved up over the term, on top of the rate
    assert (car["monthly_set_aside"], car["monthly_rate"], car["monthly_load"]) == (250, 390, 640)
    assert (car["lease_end"], car["replacement_due"]) == ("2029-03-01", "2035-03-01")
    # The Common tab divides the whole monthly load
    overview = client.get(f"{BASE_URL}/common/overview", headers=parents["dad"]).json()
    assert overview["items"][0]["monthly"] == 640
    assert overview["totals"] == {parents["mum_id"]: 320.0, parents["dad_id"]: 320.0}


def test_lease_after_the_buy_out(client, parents, monkeypatch):
    car = add_asset(client, parents["mum"], owner_id=parents["mum_id"], **LEASE).json()
    monkeypatch.setattr(common_api, "today", lambda: date(2030, 1, 1))
    car = client.get(f"{BASE_URL}/assets/{car['id']}", headers=parents["mum"]).json()
    # Down payment + 48 rates + buy-out = 35'720, set aside over the remaining 72 months for the next car
    assert (car["monthly_set_aside"], car["monthly_rate"], car["monthly_load"]) == (496.11, 0, 496.11)


def test_lease_checks(client, parents):
    mum = parents["mum"]
    assert add_asset(client, mum, owner_id=parents["mum_id"], **(LEASE | {"lease_rate": None})).status_code == 400
    # The car must be kept longer than the lease runs
    assert add_asset(client, mum, owner_id=parents["mum_id"], **(LEASE | {"lifespan_years": 4})).status_code == 400
    # A purchase has no lease fields in its output values
    bike = add_asset(client, mum, name="Bike", owner_id=parents["mum_id"]).json()
    assert (bike["kind"], bike["lease_end"], bike["monthly_rate"], bike["monthly_load"]) == ("PURCHASE", None, 0, 250)
