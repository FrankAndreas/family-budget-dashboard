"""Issues #131 and #134 (deferred from the security review of the hub login). Invented people only."""

import fake_hub
from helpers import BASE_URL, add_member, admin_headers, bearer, register, user_id

from app import hub


# 131. A made-up login is asked about once, not on every request
def test_invalid_login_asked_once(client, family_hub):
    calls = []
    real = hub.fetch_session

    def counted(tok):
        calls.append(tok)
        return real(tok)

    hub.fetch_session = counted
    try:
        for _ in range(3):
            assert client.get(f"{BASE_URL}/me", headers=bearer("tok-made-up")).status_code == 401
    finally:
        hub.fetch_session = real
    assert calls == ["tok-made-up"]


def test_no_access_is_not_remembered(client, family_hub):
    # Given access a moment later, the person gets in at once (only "no login at all" is remembered)
    family_hub.add("Max", "PARENT", access=False)
    headers = bearer(fake_hub.token("Max"))
    assert client.get(f"{BASE_URL}/me", headers=headers).status_code == 403
    family_hub.give_access("Max")
    assert client.get(f"{BASE_URL}/me", headers=headers).status_code == 200


# 134. Only a child switches their own privacy; a parent sees a person's items only where they see that person
def test_parent_cant_end_a_childs_privacy(client):
    admin = admin_headers(client)
    lena = register(client, "Lena", "CHILD")
    lena_id = user_id(client, admin, "Lena")
    client.put(f"{BASE_URL}/users/{lena_id}", json={"has_allowance": True}, headers=admin)
    assert client.patch(f"{BASE_URL}/me/privacy", json={"privacy_enabled": True}, headers=lena).status_code == 200
    refused = client.put(f"{BASE_URL}/users/{lena_id}", json={"privacy_enabled": False}, headers=admin)
    assert refused.status_code == 403


def test_items_only_of_people_one_sees(client):
    admin = admin_headers(client)
    lena = register(client, "Lena", "CHILD")
    lena_id = user_id(client, admin, "Lena")
    client.put(f"{BASE_URL}/users/{lena_id}", json={"has_allowance": True}, headers=admin)
    client.patch(f"{BASE_URL}/me/privacy", json={"privacy_enabled": True}, headers=lena)
    assert client.get(f"{BASE_URL}/users/{lena_id}/items", headers=admin).status_code == 403
    kim_id = add_member(client, "Kim")
    assert client.get(f"{BASE_URL}/users/{kim_id}/items", headers=admin).status_code == 200
