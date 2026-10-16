"""Log out everywhere: a session version per user ends all their logins at once (issue #43)."""

from datetime import timedelta

from jose import jwt

from app import auth
from helpers import BASE_URL, admin_headers, login, register, user_id


def me(client, headers):
    return client.get(f"{BASE_URL}/me", headers=headers)


def test_log_out_everywhere_ends_all_sessions(client):
    phone = register(client, "mum")
    laptop = login(client, "mum")
    assert client.post(f"{BASE_URL}/me/logout-everywhere", headers=laptop).status_code == 200
    assert me(client, phone).status_code == 401
    assert me(client, laptop).status_code == 401
    assert me(client, login(client, "mum")).status_code == 200


def test_other_people_stay_logged_in(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.post(f"{BASE_URL}/me/logout-everywhere", headers=mum)
    assert me(client, dad).status_code == 200


def test_new_pin_ends_sessions(client):
    kid = register(client, "kid", role="CHILD")
    admin = admin_headers(client)
    client.put(f"{BASE_URL}/users/{user_id(client, admin, 'kid')}", json={"pin": "4321"}, headers=admin)
    assert me(client, kid).status_code == 401
    assert me(client, login(client, "kid", "4321")).status_code == 200


def test_renaming_keeps_sessions(client):
    kid = register(client, "kid", role="CHILD")
    admin = admin_headers(client)
    client.put(f"{BASE_URL}/users/{user_id(client, admin, 'kid')}", json={"username": "Kim"}, headers=admin)
    assert me(client, kid).status_code == 200


def test_deactivating_ends_sessions(client):
    dad = register(client, "dad")
    admin = admin_headers(client)
    client.put(f"{BASE_URL}/users/{user_id(client, admin, 'dad')}", json={"is_active": False}, headers=admin)
    assert me(client, dad).status_code == 401


def test_tokens_from_before_the_update_still_work(client):
    register(client, "mum")
    uid = user_id(client, admin_headers(client), "mum")
    # A token as issued before session versions existed: no "ver" claim
    old = jwt.encode({"sub": uid, "exp": auth.now() + timedelta(hours=1)}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    assert me(client, {"Authorization": f"Bearer {old}"}).status_code == 200
