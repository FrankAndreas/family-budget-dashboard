"""Common budget: splits, shared expenses, who owes whom, settling up, monthly overview."""

import pytest

from helpers import BASE_URL, add_transaction, balance_of, category_id, create_account, create_split, register, user_id


@pytest.fixture
def parents(client):
    # The test database starts with the parent "Admin"; deactivate it so mum and dad are the two parents
    mum = register(client, "mum")
    dad = register(client, "dad")
    admin_id = user_id(client, mum, "Admin")
    client.put(f"{BASE_URL}/users/{admin_id}", json={"is_active": False}, headers=mum)
    return {"mum": mum, "dad": dad, "mum_id": user_id(client, mum, "mum"), "dad_id": user_id(client, mum, "dad")}


def halves(parents, mum=50):
    return {parents["mum_id"]: mum, parents["dad_id"]: 100 - mum}


def test_create_and_list_splits(client, parents):
    created = create_split(client, parents["mum"], "Equal", halves(parents))
    assert created.status_code == 200
    assert created.json()["shares"] == halves(parents)
    listed = client.get(f"{BASE_URL}/splits", headers=parents["dad"]).json()
    assert [s["name"] for s in listed] == ["Equal"]


def test_split_validation(client, parents):
    mum = parents["mum"]
    assert create_split(client, mum, "Bad sum", halves(parents) | {parents["dad_id"]: 40}).status_code == 400
    assert create_split(client, mum, "Missing", {parents["mum_id"]: 100}).status_code == 400
    assert create_split(client, mum, "Negative", halves(parents, mum=110)).status_code == 422
    create_split(client, mum, "Equal", halves(parents))
    assert create_split(client, mum, "Equal", halves(parents)).status_code == 400
    for i, ratio in enumerate([60, 70, 80]):
        assert create_split(client, mum, f"S{i}", halves(parents, mum=ratio)).status_code == 200
    assert create_split(client, mum, "Fifth", halves(parents, mum=90)).status_code == 400


def test_children_cannot_use_splits(client, parents):
    teen = register(client, "teen", role="CHILD", by=parents["mum"])
    assert client.get(f"{BASE_URL}/splits", headers=teen).status_code == 403
    assert create_split(client, teen, "Equal", halves(parents)).status_code == 403


def test_edit_and_delete_split(client, parents):
    split = create_split(client, parents["mum"], "Equal", halves(parents)).json()
    edited = client.put(
        f"{BASE_URL}/splits/{split['id']}",
        json={"name": "By income", "shares": halves(parents, mum=70)},
        headers=parents["dad"],
    )
    assert edited.status_code == 200 and edited.json()["shares"][parents["mum_id"]] == 70
    assert client.delete(f"{BASE_URL}/splits/{split['id']}", headers=parents["dad"]).status_code == 200
    assert client.get(f"{BASE_URL}/splits", headers=parents["mum"]).json() == []


def test_new_parent_must_be_added_when_editing(client, parents):
    split = create_split(client, parents["mum"], "Equal", halves(parents)).json()
    register(client, "grandma", by=parents["mum"])
    # Listing still works with the new parent missing
    assert client.get(f"{BASE_URL}/splits", headers=parents["mum"]).status_code == 200
    # Saving requires a percent for every active parent
    again = client.put(
        f"{BASE_URL}/splits/{split['id']}", json={"name": "Equal", "shares": halves(parents)}, headers=parents["mum"]
    )
    assert again.status_code == 400


@pytest.fixture
def setup(client, parents):
    return {
        "mum_account": create_account(client, parents["mum"], "Mum bank"),
        "dad_account": create_account(client, parents["dad"], "Dad bank"),
        "groceries": category_id(client, "Groceries"),
        "equal": create_split(client, parents["mum"], "Equal", halves(parents)).json()["id"],
        "income70": create_split(client, parents["mum"], "By income", halves(parents, mum=70)).json()["id"],
    }


def shared(client, parents, setup, amount, split="equal", who="mum", **extra):
    return add_transaction(
        client, parents[who], setup[f"{who}_account"], setup["groceries"], amount, split_id=setup[split], **extra
    )


def test_shared_expense_balance(client, parents, setup):
    paid = shared(client, parents, setup, 100)
    assert paid.status_code == 200
    assert paid.json()["split_shares"] == halves(parents)
    # Mum's account drops by the full amount
    assert client.get(f"{BASE_URL}/accounts", headers=parents["mum"]).json()[0]["balance"] == -100
    shared(client, parents, setup, 40, split="income70", who="dad")
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 22.0
    assert balance_of(client, parents["dad"], parents["dad_id"]) == -22.0


def test_editing_split_keeps_past_balances(client, parents, setup):
    shared(client, parents, setup, 100)
    client.put(
        f"{BASE_URL}/splits/{setup['equal']}",
        json={"name": "Equal", "shares": halves(parents, mum=90)},
        headers=parents["mum"],
    )
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 50.0


def test_shared_expense_rules(client, parents, setup):
    salary = category_id(client, "Salary")
    mum, account = parents["mum"], setup["mum_account"]
    assert add_transaction(client, mum, account, salary, 100, split_id=setup["equal"]).status_code == 400
    assert add_transaction(client, mum, account, setup["groceries"], 5, split_id="nope").status_code == 400
    teen = register(client, "teen", role="CHILD", by=parents["mum"])
    teen_account = create_account(client, teen, "Teen bank")
    assert (
        add_transaction(client, teen, teen_account, setup["groceries"], 5, split_id=setup["equal"]).status_code == 400
    )
    # Editing a shared expense into income is refused too
    expense = shared(client, parents, setup, 10).json()
    to_income = client.put(f"{BASE_URL}/transactions/{expense['id']}", json={"category_id": salary}, headers=mum)
    assert to_income.status_code == 400


def test_unsharing_and_deleting_update_balance(client, parents, setup):
    expense = shared(client, parents, setup, 100).json()
    url, mum = f"{BASE_URL}/transactions/{expense['id']}", parents["mum"]
    client.put(url, json={"split_id": setup["income70"]}, headers=mum)
    assert balance_of(client, mum, parents["mum_id"]) == 30.0
    client.put(url, json={"split_id": None}, headers=mum)
    assert balance_of(client, mum, parents["mum_id"]) == 0.0
    client.put(url, json={"split_id": setup["equal"]}, headers=mum)
    client.delete(url, headers=mum)
    assert balance_of(client, mum, parents["mum_id"]) == 0.0


def test_shared_expenses_visible_to_both_parents(client, parents, setup):
    shared(client, parents, setup, 100, description="Migros")
    rows = client.get(f"{BASE_URL}/common/expenses", headers=parents["dad"]).json()
    assert len(rows) == 1
    assert rows[0]["description"] == "Migros" and rows[0]["payer_id"] == parents["mum_id"]
    assert rows[0]["amount"] == 100 and rows[0]["split_name"] == "Equal"
    assert rows[0]["shares"] == {parents["mum_id"]: 50.0, parents["dad_id"]: 50.0}
    # Dad still can't open Mum's account
    response = client.get(f"{BASE_URL}/accounts/{setup['mum_account']}/transactions", headers=parents["dad"])
    assert response.status_code == 403


def test_three_parents(client, parents, setup):
    shared(client, parents, setup, 90)
    register(client, "grandma", by=parents["mum"])
    grandma_id = user_id(client, parents["mum"], "grandma")
    assert balance_of(client, parents["mum"], grandma_id) == 0.0
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 45.0


def test_deleted_split_keeps_balance(client, parents, setup):
    expense = shared(client, parents, setup, 100).json()
    assert client.delete(f"{BASE_URL}/splits/{setup['equal']}", headers=parents["mum"]).status_code == 200
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 50.0
    # Still a shared expense, with the percentages it was booked with; the deleted split is no longer named
    [listed] = [
        e
        for e in client.get(f"{BASE_URL}/common/expenses", headers=parents["mum"]).json()
        if e["transaction_id"] == expense["id"]
    ]
    assert listed["split_name"] is None and listed["amount"] == 100
    edited = client.put(
        f"{BASE_URL}/transactions/{expense['id']}", json={"description": "Coop"}, headers=parents["mum"]
    )
    assert edited.status_code == 200


def settle(client, headers, parents, setup, amount):
    return client.post(
        f"{BASE_URL}/settlements",
        json={
            "from_user_id": parents["dad_id"],
            "to_user_id": parents["mum_id"],
            "amount": amount,
            "from_account_id": setup["dad_account"],
            "to_account_id": setup["mum_account"],
        },
        headers=headers,
    )


def test_settle_up(client, parents, setup):
    shared(client, parents, setup, 100)
    assert settle(client, parents["dad"], parents, setup, 50).status_code == 200
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 0.0
    assert client.get(f"{BASE_URL}/accounts", headers=parents["mum"]).json()[0]["balance"] == -50.0
    assert client.get(f"{BASE_URL}/accounts", headers=parents["dad"]).json()[0]["balance"] == -50.0
    assert [s["amount"] for s in client.get(f"{BASE_URL}/settlements", headers=parents["mum"]).json()] == [50.0]
    # The transfer can't be deleted on its own (it would unbalance the settlement)
    mum_transactions = client.get(f"{BASE_URL}/accounts/{setup['mum_account']}/transactions", headers=parents["mum"])
    transfer = next(t for t in mum_transactions.json() if t["description"] == "Settle up")
    assert client.delete(f"{BASE_URL}/transactions/{transfer['id']}", headers=parents["mum"]).status_code == 400


def test_delete_settlement_undoes_it(client, parents, setup):
    shared(client, parents, setup, 100)
    settled = settle(client, parents["mum"], parents, setup, 50).json()
    assert client.delete(f"{BASE_URL}/settlements/{settled['id']}", headers=parents["mum"]).status_code == 200
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 50.0
    assert client.get(f"{BASE_URL}/accounts", headers=parents["dad"]).json()[0]["balance"] == 0.0


def test_settlement_rules(client, parents, setup):
    assert settle(client, parents["dad"], parents, setup, 0).status_code == 422
    wrong_account = settle(client, parents["dad"], parents, setup | {"dad_account": setup["mum_account"]}, 10)
    assert wrong_account.status_code == 400
    teen = register(client, "teen", role="CHILD", by=parents["mum"])
    assert settle(client, teen, parents, setup, 10).status_code == 403
    same = client.post(
        f"{BASE_URL}/settlements",
        json={
            "from_user_id": parents["mum_id"],
            "to_user_id": parents["mum_id"],
            "amount": 5,
            "from_account_id": setup["mum_account"],
            "to_account_id": setup["mum_account"],
        },
        headers=parents["mum"],
    )
    assert same.status_code == 400


def test_deactivated_parent_can_still_settle(client, parents, setup):
    shared(client, parents, setup, 100)
    client.put(f"{BASE_URL}/users/{parents['dad_id']}", json={"is_active": False}, headers=parents["mum"])
    # The open balance stays visible, and can be settled
    assert balance_of(client, parents["mum"], parents["dad_id"]) == -50.0
    assert settle(client, parents["mum"], parents, setup, 50).status_code == 200
    assert balance_of(client, parents["mum"], parents["mum_id"]) == 0.0
