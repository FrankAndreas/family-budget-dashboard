"""E-mail addresses of family members (issue #57): the allow list for forwarded receipt mails."""

from helpers import remove_id_from_hub, BASE_URL, admin_headers, register, user_id

from app import database, emails_api, models

EMAILS = f"{BASE_URL}/emails"


def add(client, headers, person_id, address):
    return client.post(f"{BASE_URL}/users/{person_id}/emails", json={"address": address}, headers=headers)


def test_parent_adds_and_lists_addresses(client):
    mum = register(client, "mum")
    mum_id = user_id(client, mum, "mum")
    response = add(client, mum, mum_id, "  Mum@Example.CH ")
    assert response.status_code == 200, response.text
    assert response.json()["address"] == "mum@example.ch"
    assert [(e["user_id"], e["address"]) for e in client.get(EMAILS, headers=mum).json()] == [
        (mum_id, "mum@example.ch")
    ]


def test_several_addresses_per_person(client):
    mum = register(client, "mum")
    mum_id = user_id(client, mum, "mum")
    add(client, mum, mum_id, "mum@example.ch")
    add(client, mum, mum_id, "mum.work@example.ch")
    assert sorted(e["address"] for e in client.get(EMAILS, headers=mum).json()) == [
        "mum.work@example.ch",
        "mum@example.ch",
    ]


def test_address_belongs_to_one_person(client):
    mum = register(client, "mum")
    register(client, "dad")
    add(client, mum, user_id(client, mum, "mum"), "family@example.ch")
    response = add(client, mum, user_id(client, mum, "dad"), "FAMILY@example.ch")
    assert response.status_code == 400
    assert response.json()["detail"] == "That e-mail address is already registered"


def test_invalid_address(client):
    mum = register(client, "mum")
    for address in ("not-an-address", "a@b", "two words@example.ch", ""):
        response = add(client, mum, user_id(client, mum, "mum"), address)
        assert response.status_code in (400, 422), address
    assert add(client, mum, user_id(client, mum, "mum"), "a@b").json()["detail"] == "That is not an e-mail address"


def test_unknown_person(client):
    assert add(client, admin_headers(client), "no-such-person", "x@example.ch").status_code == 404


def test_children_cannot_manage(client):
    mum = register(client, "mum")
    kid = register(client, "kid", role="CHILD", by=mum)
    kid_id = user_id(client, mum, "kid")
    added = add(client, mum, kid_id, "kid@example.ch").json()
    assert client.get(EMAILS, headers=kid).status_code == 403
    assert add(client, kid, kid_id, "kid2@example.ch").status_code == 403
    response = client.delete(f"{EMAILS}/{added['id']}", headers=kid)
    assert response.status_code == 403
    assert response.json()["detail"] == "Only parents can manage e-mail addresses"


def test_delete_address(client):
    mum = register(client, "mum")
    added = add(client, mum, user_id(client, mum, "mum"), "mum@example.ch").json()
    assert client.delete(f"{EMAILS}/{added['id']}", headers=mum).json() == {"deleted": added["id"]}
    assert client.get(EMAILS, headers=mum).json() == []
    assert client.delete(f"{EMAILS}/{added['id']}", headers=mum).status_code == 404


def test_removing_a_person_removes_their_addresses(client):
    mum = register(client, "mum")
    register(client, "dad")
    dad_id = user_id(client, mum, "dad")
    add(client, mum, dad_id, "dad@example.ch")
    remove_id_from_hub(dad_id)
    assert client.delete(f"{BASE_URL}/users/{dad_id}", headers=mum).status_code == 200
    assert client.get(EMAILS, headers=mum).json() == []


def test_person_for(client):
    mum = register(client, "mum")
    add(client, mum, user_id(client, mum, "mum"), "mum@example.ch")
    with database.SessionLocal() as db:
        assert emails_api.person_for(db, "MUM@example.ch").username == "mum"
        assert emails_api.person_for(db, "other@example.ch") is None
        db.query(models.User).filter(models.User.username == "mum").one().is_active = False
        db.commit()
        assert emails_api.person_for(db, "mum@example.ch") is None
