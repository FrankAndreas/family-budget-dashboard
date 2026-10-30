"""Parents' (and allowance children's) finances are private unless shared with a parent (view or edit)."""

import pytest

from helpers import add_member, BASE_URL, add_transaction, category_id, create_account, register, user_id


@pytest.fixture
def parents(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    return {
        "mum": mum,
        "dad": dad,
        "mum_id": user_id(client, mum, "mum"),
        "dad_id": user_id(client, mum, "dad"),
        "mum_account": create_account(client, mum, "Mum bank"),
        "dad_account": create_account(client, dad, "Dad bank"),
    }


def share(client, headers, grantee_id, level):
    return client.put(f"{BASE_URL}/shares/{grantee_id}", json={"level": level}, headers=headers)


def account_names(client, headers):
    return sorted(a["name"] for a in client.get(f"{BASE_URL}/accounts", headers=headers).json())


def test_parents_private_by_default(client, parents):
    assert account_names(client, parents["mum"]) == ["Mum bank"]
    response = client.get(f"{BASE_URL}/accounts/{parents['dad_account']}/transactions", headers=parents["mum"])
    assert response.status_code == 403
    # Still listed as family members (needed for splits and the share setting)
    names = {u["username"] for u in client.get(f"{BASE_URL}/users", headers=parents["mum"]).json()}
    assert {"Admin", "mum", "dad"} <= names


def test_view_share_is_read_only(client, parents):
    assert share(client, parents["dad"], parents["mum_id"], "VIEW").status_code == 200
    assert account_names(client, parents["mum"]) == ["Dad bank", "Mum bank"]
    groceries = category_id(client, "Groceries")
    assert add_transaction(client, parents["mum"], parents["dad_account"], groceries, 10).status_code == 403
    renamed = client.put(f"{BASE_URL}/accounts/{parents['dad_account']}", json={"name": "x"}, headers=parents["mum"])
    assert renamed.status_code == 403
    budgets = client.get(f"{BASE_URL}/budgets", params={"user_id": parents["dad_id"]}, headers=parents["mum"])
    assert budgets.status_code == 200
    on_behalf = client.post(
        f"{BASE_URL}/budgets",
        json={"category_id": groceries, "limit": 100, "user_id": parents["dad_id"]},
        headers=parents["mum"],
    )
    assert on_behalf.status_code == 403


def test_edit_share_delegates(client, parents):
    share(client, parents["dad"], parents["mum_id"], "EDIT")
    groceries = category_id(client, "Groceries")
    expense = add_transaction(client, parents["mum"], parents["dad_account"], groceries, 10)
    assert expense.status_code == 200
    assert client.delete(f"{BASE_URL}/transactions/{expense.json()['id']}", headers=parents["mum"]).status_code == 200

    account = client.post(
        f"{BASE_URL}/accounts",
        json={"name": "Dad cash", "type": "CASH", "user_id": parents["dad_id"]},
        headers=parents["mum"],
    )
    assert account.status_code == 200 and account.json()["user_id"] == parents["dad_id"]
    budget = client.post(
        f"{BASE_URL}/budgets",
        json={"category_id": groceries, "limit": 100, "user_id": parents["dad_id"]},
        headers=parents["mum"],
    )
    assert budget.status_code == 200 and budget.json()["user_id"] == parents["dad_id"]
    assert client.delete(f"{BASE_URL}/budgets/{budget.json()['id']}", headers=parents["mum"]).status_code == 200


def test_share_can_be_revoked(client, parents):
    share(client, parents["dad"], parents["mum_id"], "EDIT")
    assert share(client, parents["dad"], parents["mum_id"], "NONE").status_code == 200
    assert account_names(client, parents["mum"]) == ["Mum bank"]
    assert client.get(f"{BASE_URL}/shares", headers=parents["mum"]).json() == []


def test_shares_listed_for_both_parents(client, parents):
    share(client, parents["dad"], parents["mum_id"], "VIEW")
    expected = [{"owner_id": parents["dad_id"], "grantee_id": parents["mum_id"], "level": "VIEW"}]
    assert client.get(f"{BASE_URL}/shares", headers=parents["mum"]).json() == expected
    assert client.get(f"{BASE_URL}/shares", headers=parents["dad"]).json() == expected


def test_share_only_with_a_parent(client, parents):
    teen = register(client, "teen", role="CHILD")
    teen_id = user_id(client, parents["mum"], "teen")
    timmy = {"id": add_member(client, "timmy"), "username": "timmy"}
    register(client, "sis", role="CHILD")
    sis_id = user_id(client, parents["mum"], "sis")
    assert share(client, parents["mum"], teen_id, "VIEW").status_code == 400
    assert share(client, parents["mum"], timmy["id"], "VIEW").status_code == 400
    assert share(client, parents["mum"], parents["mum_id"], "VIEW").status_code == 400
    assert share(client, teen, sis_id, "VIEW").status_code == 400
    assert share(client, parents["mum"], parents["dad_id"], "ALL").status_code == 422


def test_budgets_belong_to_one_parent(client, parents):
    groceries = category_id(client, "Groceries")
    mine = client.post(f"{BASE_URL}/budgets", json={"category_id": groceries, "limit": 50}, headers=parents["mum"])
    assert client.get(f"{BASE_URL}/budgets", headers=parents["dad"]).json() == []
    assert client.delete(f"{BASE_URL}/budgets/{mine.json()['id']}", headers=parents["dad"]).status_code == 404
    assert client.delete(f"{BASE_URL}/budgets/{mine.json()['id']}", headers=parents["mum"]).status_code == 200


def test_parent_reads_but_does_not_write_child_account(client, parents):
    teen = register(client, "teen", role="CHILD")
    teen_account = create_account(client, teen, "Teen bank")
    groceries = category_id(client, "Groceries")
    assert add_transaction(client, parents["mum"], teen_account, groceries, 5).status_code == 403
    assert client.get(f"{BASE_URL}/accounts/{teen_account}/transactions", headers=parents["mum"]).status_code == 200


def test_child_lets_parent_manage(client, parents):
    teen = register(client, "teen", role="CHILD")
    teen_account = create_account(client, teen, "Teen bank")
    groceries = category_id(client, "Groceries")
    assert share(client, teen, parents["mum_id"], "EDIT").status_code == 200
    assert add_transaction(client, parents["mum"], teen_account, groceries, 5).status_code == 200
    assert add_transaction(client, parents["dad"], teen_account, groceries, 5).status_code == 403
    teen_id = user_id(client, parents["mum"], "teen")
    budget = client.post(
        f"{BASE_URL}/budgets", json={"category_id": groceries, "limit": 20, "user_id": teen_id}, headers=parents["mum"]
    )
    assert budget.status_code == 200


def test_child_can_hide_from_one_parent(client, parents):
    teen = register(client, "teen", role="CHILD")
    create_account(client, teen, "Teen bank")
    assert share(client, teen, parents["dad_id"], "NONE").status_code == 200
    assert "Teen bank" in account_names(client, parents["mum"])
    assert "Teen bank" not in account_names(client, parents["dad"])
    assert client.get(f"{BASE_URL}/shares", headers=teen).json()[0]["level"] == "NONE"
    # The child sees the parents in the family list, to choose whom to share with
    names = {u["username"] for u in client.get(f"{BASE_URL}/users", headers=teen).json()}
    assert {"mum", "dad", "teen"} <= names


def test_deleting_parent_removes_their_shares(client, parents):
    share(client, parents["dad"], parents["mum_id"], "VIEW")
    client.delete(f"{BASE_URL}/users/{parents['dad_id']}", headers=parents["mum"])
    assert client.get(f"{BASE_URL}/shares", headers=parents["mum"]).json() == []
