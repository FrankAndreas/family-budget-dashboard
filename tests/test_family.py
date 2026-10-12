"""Family model: shared parent household, children with own allowance, dependent children tagged on expenses."""

import pytest

from helpers import BASE_URL, add_transaction, category_id, create_account, login, register, user_id


@pytest.fixture
def family(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    teen = register(client, "teen", role="CHILD")
    timmy = client.post(f"{BASE_URL}/members", json={"username": "timmy"}, headers=mum).json()
    return {
        "mum": mum,
        "dad": dad,
        "teen": teen,
        "timmy_id": timmy["id"],
        "teen_id": user_id(client, mum, "teen"),
        "mum_account": create_account(client, mum, "Mum bank"),
        "dad_account": create_account(client, dad, "Dad bank"),
        "teen_account": create_account(client, teen, "Teen bank"),
    }


def test_dependent_child_has_no_login(client, family):
    assert login(client, "timmy", "") == 401
    assert login(client, "timmy", "1234") == 401


def test_only_parents_add_members(client, family):
    assert client.post(f"{BASE_URL}/members", json={"username": "x"}, headers=family["teen"]).status_code == 403


def test_parents_share_household(client, family):
    names = sorted(a["name"] for a in client.get(f"{BASE_URL}/accounts", headers=family["mum"]).json())
    assert names == ["Dad bank", "Mum bank", "Teen bank"]
    assert (
        add_transaction(client, family["mum"], family["dad_account"], category_id(client, "Groceries"), 10).status_code
        == 200
    )


def test_child_sees_only_own(client, family):
    names = [a["name"] for a in client.get(f"{BASE_URL}/accounts", headers=family["teen"]).json()]
    assert names == ["Teen bank"]


def test_tagging_rules(client, family):
    clothing = category_id(client, "Clothing")
    tagged = add_transaction(client, family["mum"], family["mum_account"], clothing, 80, member_id=family["timmy_id"])
    assert tagged.json()["member_id"] == family["timmy_id"]
    # Only dependents can be tagged, and only on household accounts
    assert (
        add_transaction(
            client, family["mum"], family["mum_account"], clothing, 5, member_id=family["teen_id"]
        ).status_code
        == 400
    )
    assert (
        add_transaction(
            client, family["mum"], family["teen_account"], clothing, 5, member_id=family["timmy_id"]
        ).status_code
        == 400
    )
    untagged = client.put(
        f"{BASE_URL}/transactions/{tagged.json()['id']}", json={"member_id": None}, headers=family["mum"]
    ).json()
    assert untagged["member_id"] is None


def test_household_and_child_budgets(client, family):
    groceries, clothing = category_id(client, "Groceries"), category_id(client, "Clothing")
    household = client.post(
        f"{BASE_URL}/budgets", json={"category_id": groceries, "limit": 400}, headers=family["mum"]
    ).json()
    own = client.post(f"{BASE_URL}/budgets", json={"category_id": clothing, "limit": 50}, headers=family["teen"]).json()

    assert [b["id"] for b in client.get(f"{BASE_URL}/budgets", headers=family["dad"]).json()] == [household["id"]]
    assert [b["id"] for b in client.get(f"{BASE_URL}/budgets", headers=family["teen"]).json()] == [own["id"]]
    inspected = client.get(f"{BASE_URL}/budgets", params={"user_id": family["teen_id"]}, headers=family["mum"]).json()
    assert [b["id"] for b in inspected] == [own["id"]]

    mum_id = user_id(client, family["mum"], "mum")
    assert client.get(f"{BASE_URL}/budgets", params={"user_id": mum_id}, headers=family["teen"]).status_code == 403
    # Parents manage household budgets together, but only inspect a child's
    assert client.delete(f"{BASE_URL}/budgets/{own['id']}", headers=family["mum"]).status_code == 404
    assert client.delete(f"{BASE_URL}/budgets/{household['id']}", headers=family["dad"]).status_code == 200


def test_switching_allowance(client, family):
    timmy, mum = family["timmy_id"], family["mum"]
    assert client.put(f"{BASE_URL}/users/{timmy}", json={"has_allowance": True}, headers=mum).status_code == 400
    assert (
        client.put(f"{BASE_URL}/users/{timmy}", json={"has_allowance": True, "pin": "5678"}, headers=mum).status_code
        == 200
    )
    assert isinstance(login(client, "timmy", "5678"), dict)
    # A child with own accounts can't become a dependent until those are gone
    assert (
        client.put(f"{BASE_URL}/users/{family['teen_id']}", json={"has_allowance": False}, headers=mum).status_code
        == 400
    )
    dad_id = user_id(client, mum, "dad")
    assert client.put(f"{BASE_URL}/users/{dad_id}", json={"has_allowance": False}, headers=mum).status_code == 400


def test_deleting_child_keeps_tagged_expense(client, family):
    expense = add_transaction(
        client, family["mum"], family["mum_account"], category_id(client, "Clothing"), 20, member_id=family["timmy_id"]
    ).json()
    client.delete(f"{BASE_URL}/users/{family['timmy_id']}", headers=family["mum"])
    remaining = client.get(f"{BASE_URL}/accounts/{family['mum_account']}/transactions", headers=family["mum"]).json()
    kept = [t for t in remaining if t["id"] == expense["id"]]
    assert len(kept) == 1
    assert kept[0]["member_id"] is None
