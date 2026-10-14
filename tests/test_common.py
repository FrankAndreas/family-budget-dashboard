"""Common budget: splits, shared expenses, who owes whom, settling up, monthly overview."""

import pytest

from helpers import BASE_URL, create_split, register, user_id


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
