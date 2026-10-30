"""Each person's language (issue #50): chosen in the family hub, German by default, used for error messages."""

from helpers import BASE_URL, login, register, set_language

from app import i18n


def me(client, headers):
    return client.get(f"{BASE_URL}/me", headers=headers).json()


def test_unsupported_default_falls_back_to_german(monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "fr")
    assert i18n.default_language() == "de"
    monkeypatch.delenv("DEFAULT_LANGUAGE")
    assert i18n.default_language() == "de"


def test_language_comes_from_the_hub(client):
    mum = register(client, "mum")
    assert me(client, mum)["language"] == "en"
    set_language(mum, "de")
    assert me(client, mum)["language"] == "de"
    # Error messages too
    assert client.get(f"{BASE_URL}/accounts/nope/transactions", headers=mum).json()["detail"] == "Konto nicht gefunden"


def test_children_have_their_own_language(client):
    kid = register(client, "kid", role="CHILD")
    set_language(kid, "de")
    assert me(client, kid)["language"] == "de"
    assert me(client, login(client, "Admin"))["language"] == "en"


def test_accept_language_parsing():
    assert i18n.from_header("de-CH,de;q=0.9,en;q=0.8") == "de"
    assert i18n.from_header("en-US,en;q=0.9") == "en"
    assert i18n.from_header("fr-CH, en;q=0.5, de;q=0.7") == "de"
    assert i18n.from_header("fr") is None
    assert i18n.from_header("") is None
    assert i18n.from_header(None) is None
    assert i18n.from_header("de;q=garbage, en") == "en"
