"""Family model: private parent finances, children with own allowance, dependent children tagged on expenses."""

import pytest

from helpers import add_member, BASE_URL, add_transaction, category_id, create_account, register, user_id


@pytest.fixture
def family(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    teen = register(client, "teen", role="CHILD")
    timmy = {"id": add_member(client, "timmy"), "username": "timmy"}
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


def test_parents_are_private(client, family):
    names = sorted(a["name"] for a in client.get(f"{BASE_URL}/accounts", headers=family["mum"]).json())
    assert names == ["Mum bank", "Teen bank"]
    assert (
        add_transaction(client, family["mum"], family["dad_account"], category_id(client, "Groceries"), 10).status_code
        == 403
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
            client, family["teen"], family["teen_account"], clothing, 5, member_id=family["timmy_id"]
        ).status_code
        == 400
    )
    untagged = client.put(
        f"{BASE_URL}/transactions/{tagged.json()['id']}", json={"member_id": None}, headers=family["mum"]
    ).json()
    assert untagged["member_id"] is None


def test_parent_and_child_budgets(client, family):
    groceries, clothing = category_id(client, "Groceries"), category_id(client, "Clothing")
    mums = client.post(
        f"{BASE_URL}/budgets", json={"category_id": groceries, "limit": 400}, headers=family["mum"]
    ).json()
    own = client.post(f"{BASE_URL}/budgets", json={"category_id": clothing, "limit": 50}, headers=family["teen"]).json()

    assert client.get(f"{BASE_URL}/budgets", headers=family["dad"]).json() == []
    assert [b["id"] for b in client.get(f"{BASE_URL}/budgets", headers=family["mum"]).json()] == [mums["id"]]
    assert [b["id"] for b in client.get(f"{BASE_URL}/budgets", headers=family["teen"]).json()] == [own["id"]]
    inspected = client.get(f"{BASE_URL}/budgets", params={"user_id": family["teen_id"]}, headers=family["mum"]).json()
    assert [b["id"] for b in inspected] == [own["id"]]

    mum_id = user_id(client, family["mum"], "mum")
    assert client.get(f"{BASE_URL}/budgets", params={"user_id": mum_id}, headers=family["teen"]).status_code == 403
    # Parents only inspect a child's budgets, and don't touch each other's without a share
    assert client.delete(f"{BASE_URL}/budgets/{own['id']}", headers=family["mum"]).status_code == 404
    assert client.delete(f"{BASE_URL}/budgets/{mums['id']}", headers=family["dad"]).status_code == 404


def test_switching_allowance(client, family):
    timmy, mum = family["timmy_id"], family["mum"]
    # No PIN needed any more: the child logs in through the family hub
    assert client.put(f"{BASE_URL}/users/{timmy}", json={"has_allowance": True}, headers=mum).status_code == 200
    assert (
        client.put(f"{BASE_URL}/users/{timmy}", json={"has_allowance": True, "pin": "5678"}, headers=mum).status_code
        == 422
    )
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
