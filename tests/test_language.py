"""Each person's language (issue #50): stored in users.settings, German by default, used for error messages."""

from helpers import BASE_URL, login, register

from app import i18n


def me(client, headers):
    return client.get(f"{BASE_URL}/me", headers=headers).json()


def test_language_defaults_to_the_configured_default(client, monkeypatch):
    mum = register(client, "mum")
    assert me(client, mum)["language"] == "en"
    monkeypatch.setenv("DEFAULT_LANGUAGE", "de")
    assert me(client, mum)["language"] == "de"


def test_unsupported_default_falls_back_to_german(monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "fr")
    assert i18n.default_language() == "de"
    monkeypatch.delenv("DEFAULT_LANGUAGE")
    assert i18n.default_language() == "de"


def test_set_language(client):
    mum = register(client, "mum")
    response = client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    assert response.status_code == 200 and response.json()["language"] == "de"
    assert me(client, mum)["language"] == "de"
    assert me(client, login(client, "mum"))["language"] == "de"


def test_other_settings_are_kept(client):
    mum = register(client, "mum")
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    client.patch(f"{BASE_URL}/me/language", json={"language": "en"}, headers=mum)
    assert me(client, mum)["language"] == "en"


def test_unknown_language_is_rejected(client):
    mum = register(client, "mum")
    assert client.patch(f"{BASE_URL}/me/language", json={"language": "fr"}, headers=mum).status_code == 422


def test_children_choose_their_own_language(client):
    kid = register(client, "kid", role="CHILD")
    assert client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=kid).status_code == 200


def test_accept_language_parsing():
    assert i18n.from_header("de-CH,de;q=0.9,en;q=0.8") == "de"
    assert i18n.from_header("en-US,en;q=0.9") == "en"
    assert i18n.from_header("fr-CH, en;q=0.5, de;q=0.7") == "de"
    assert i18n.from_header("fr") is None
    assert i18n.from_header("") is None
    assert i18n.from_header(None) is None
    assert i18n.from_header("de;q=garbage, en") == "en"
