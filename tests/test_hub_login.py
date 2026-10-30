"""Logging in through the family hub, and the people the hub gives this app (spec 2026-10-30, part B)."""

import threading

import fake_hub
from helpers import BASE_URL, ADMIN, admin_headers, bearer, create_account, register, user_id

from app import database, hub_people, models


def me(client, headers=None, **kwargs):
    return client.get(f"{BASE_URL}/me", headers=headers, **kwargs)


def test_no_token_401(client):
    assert me(client).status_code == 401


def test_unknown_token_401(client):
    assert me(client, bearer("tok-nobody")).status_code == 401


def test_cookie_login_needs_header_for_changes(client):
    client.cookies.set("hub_session", fake_hub.token(ADMIN))
    assert me(client).json()["username"] == ADMIN
    body = {"name": "Bank", "type": "BANK"}
    # Another site could make the browser send the cookie, but not this header
    refused = client.post(f"{BASE_URL}/accounts", json=body)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "This request needs the app's own header."
    assert client.post(f"{BASE_URL}/accounts", json=body, headers={"X-Requested-With": "budget"}).status_code == 200


def test_no_access_403(client, family_hub):
    family_hub.add("Max", "PARENT", access=False)
    response = me(client, bearer(fake_hub.token("Max")))
    assert response.status_code == 403
    assert response.json()["code"] == "no_access"


def test_hub_down_503(client, family_hub):
    family_hub.down = True
    response = me(client, admin_headers(client))
    assert response.status_code == 503
    assert response.json()["code"] == "hub_unavailable"


def test_new_person_appears(client, family_hub):
    family_hub.add("Lena", "CHILD")
    found = {u["username"]: u for u in client.get(f"{BASE_URL}/users", headers=admin_headers(client)).json()}
    assert found["Lena"]["role"] == "CHILD"
    assert found["Lena"]["has_allowance"] is False


def test_existing_row_linked_by_name(client, family_hub):
    with database.SessionLocal() as db:
        before = db.query(models.User).filter(models.User.username == ADMIN).one()
        assert before.hub_id is None
    headers = admin_headers(client)
    account = create_account(client, headers)
    with database.SessionLocal() as db:
        after = db.query(models.User).filter(models.User.username == ADMIN).one()
        assert (after.id, after.hub_id) == (before.id, family_hub.people[ADMIN].id)
        assert db.query(models.Account).filter(models.Account.id == account).one().user_id == before.id


def test_removed_person_hidden_and_back(client, family_hub):
    lena = register(client, "Lena", "CHILD")
    account = create_account(client, lena)
    family_hub.remove_access("Lena")
    admin = admin_headers(client)
    assert "Lena" not in [u["username"] for u in client.get(f"{BASE_URL}/users", headers=admin).json()]
    assert me(client, lena).status_code == 403
    family_hub.give_access("Lena")
    assert "Lena" in [u["username"] for u in client.get(f"{BASE_URL}/users", headers=admin).json()]
    assert account in [a["id"] for a in client.get(f"{BASE_URL}/accounts", headers=lena).json()]


def test_rename_follows_hub(client, family_hub):
    register(client, "Lena", "CHILD")
    lena_id = user_id(client, admin_headers(client), "Lena")
    family_hub.rename("Lena", "Lea")
    assert user_id(client, admin_headers(client), "Lea") == lena_id


def test_names_swapped(client, family_hub):
    register(client, "Lena", "CHILD")
    register(client, "Max", "CHILD")
    admin = admin_headers(client)
    lena, max_ = user_id(client, admin, "Lena"), user_id(client, admin, "Max")
    family_hub.rename("Lena", "Tmp")
    family_hub.rename("Max", "Lena")
    family_hub.rename("Tmp", "Max")
    assert (user_id(client, admin, "Max"), user_id(client, admin, "Lena")) == (lena, max_)


def test_role_and_language_follow_hub(client, family_hub):
    register(client, "Lena", "CHILD")
    family_hub.set_role("Lena", "PARENT")
    family_hub.set_language("Lena", "de")
    found = me(client, bearer(fake_hub.token("Lena"))).json()
    assert (found["role"], found["language"]) == ("PARENT", "de")


def test_concurrent_first_requests(client, family_hub):
    family_hub.add("Lena", "CHILD")
    family_hub.add("Max", "CHILD")
    errors = []

    def refresh():
        try:
            with database.SessionLocal() as db:
                hub_people.refresh(db, fake_hub.token(ADMIN), force=True)
        except Exception as error:  # noqa: BLE001 - any error fails the test below
            errors.append(error)

    threads = [threading.Thread(target=refresh) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    with database.SessionLocal() as db:
        names = sorted(u.username for u in db.query(models.User))
    assert names == ["Admin", "Lena", "Max"]


def test_logout_clears_cookie(client, monkeypatch):
    monkeypatch.setenv("COOKIE_DOMAIN", "local.example.ch")
    response = client.post(f"{BASE_URL}/logout", headers={"X-Requested-With": "budget"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("hub_session=")
    assert "Domain=local.example.ch" in cookie
    assert "Max-Age=0" in cookie or "expires=Thu, 01 Jan 1970" in cookie


def test_hub_login_url(client, monkeypatch):
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://home.local.example.ch")
    assert client.get(f"{BASE_URL}/hub").json() == {"login_url": "https://home.local.example.ch"}


def test_removed_endpoints(client):
    admin = admin_headers(client)
    assert client.post(f"{BASE_URL}/login", json={"username": ADMIN, "pin": "0000"}).status_code in (404, 405)
    assert client.post(f"{BASE_URL}/users", json={"username": "X", "pin": "1234"}, headers=admin).status_code in (
        404,
        405,
    )
    assert client.post(f"{BASE_URL}/members", json={"username": "X"}, headers=admin).status_code in (404, 405)
    assert client.post(f"{BASE_URL}/me/logout-everywhere", headers=admin).status_code in (404, 405)
    assert client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=admin).status_code in (404, 405)
    admin_id = user_id(client, admin, ADMIN)
    assert client.put(f"{BASE_URL}/users/{admin_id}", json={"username": "Boss"}, headers=admin).status_code == 422
