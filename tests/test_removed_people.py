"""People the family hub no longer lists for this app: hidden here with their data; parents may delete it
(spec 2026-10-30, part B)."""

import csv
import io
import zipfile

from helpers import (
    BASE_URL,
    add_member,
    add_transaction,
    category_id,
    create_account,
    register,
    remove_from_hub,
    user_id,
)


def names(client, headers):
    return [u["username"] for u in client.get(f"{BASE_URL}/users", headers=headers).json()]


def members_csv(client, headers):
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"{BASE_URL}/export/analysis.zip", headers=headers).content))
    return [row["name"] for row in csv.DictReader(io.StringIO(archive.read("members.csv").decode()))]


def test_removed_not_listed(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    dad_account = create_account(client, dad, "Dad bank")
    assert (
        client.put(f"{BASE_URL}/shares/{user_id(client, mum, 'mum')}", json={"level": "VIEW"}, headers=dad).status_code
        == 200
    )
    assert dad_account in [a["id"] for a in client.get(f"{BASE_URL}/accounts", headers=mum).json()]
    remove_from_hub("dad")
    assert "dad" not in names(client, mum)
    assert client.get(f"{BASE_URL}/shares", headers=mum).json() == []
    # Their money is hidden too: accounts and the export
    assert dad_account not in [a["id"] for a in client.get(f"{BASE_URL}/accounts", headers=mum).json()]
    assert "dad" not in members_csv(client, mum)
    assert "mum" in members_csv(client, mum)


def test_removed_listed_for_parents(client):
    mum = register(client, "mum")
    teen = register(client, "teen", role="CHILD")
    kid = add_member(client, "kid")
    remove_from_hub("kid")
    found = client.get(f"{BASE_URL}/users/removed", headers=mum).json()
    assert found == [{"id": kid, "username": "kid", "role": "CHILD"}]
    assert client.get(f"{BASE_URL}/users/removed", headers=teen).status_code == 403


def test_delete_needs_removal_first(client):
    mum = register(client, "mum")
    kid = add_member(client, "kid")
    response = client.delete(f"{BASE_URL}/users/{kid}", headers=mum)
    assert response.status_code == 409
    assert response.json()["detail"] == "Remove the person's access in the family hub first."


def test_delete_removed_member(client):
    mum = register(client, "mum")
    teen = register(client, "teen", role="CHILD")
    kid = add_member(client, "kid")
    teen_id = user_id(client, mum, "teen")
    teen_account = create_account(client, teen, "Teen bank")
    add_transaction(client, teen, teen_account, category_id(client, "Groceries"), 5)
    mum_account = create_account(client, mum, "Mum bank")
    tagged = add_transaction(client, mum, mum_account, category_id(client, "Clothing"), 30, member_id=kid).json()
    remove_from_hub("teen")
    remove_from_hub("kid")
    assert client.delete(f"{BASE_URL}/users/{teen_id}", headers=mum).status_code == 200
    assert client.delete(f"{BASE_URL}/users/{kid}", headers=mum).status_code == 200
    assert client.get(f"{BASE_URL}/users/removed", headers=mum).json() == []
    # The household expense stays, without the tag
    kept = client.get(f"{BASE_URL}/accounts/{mum_account}/transactions", headers=mum).json()
    assert [(t["id"], t["member_id"]) for t in kept] == [(tagged["id"], None)]


def test_parent_listing_people_asks_the_hub(client, family_hub):
    mum = register(client, "mum")
    add_member(client, "kid")
    # Changed in the hub a moment ago, inside the app's minute between refreshes
    family_hub.access.discard("kid")
    assert "kid" not in names(client, mum)
