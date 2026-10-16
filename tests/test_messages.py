"""Error messages in the caller's language (issue #50)."""

import re
import string

from helpers import BASE_URL, register

from app import messages

WRONG = {"username": "nobody", "pin": "9999"}


def test_wrong_pin_before_login_follows_the_browser(client):
    german = client.post(f"{BASE_URL}/login", json=WRONG, headers={"Accept-Language": "de-CH,de;q=0.9"})
    english = client.post(f"{BASE_URL}/login", json=WRONG, headers={"Accept-Language": "en-US"})
    assert german.json()["detail"] == messages.MESSAGES["de"]["wrong_login"]
    assert english.json()["detail"] == messages.MESSAGES["en"]["wrong_login"]


def test_without_a_header_the_default_applies(client, monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "de")
    assert client.post(f"{BASE_URL}/login", json=WRONG).json()["detail"] == messages.MESSAGES["de"]["wrong_login"]


def test_the_persons_setting_beats_the_browser(client):
    mum = register(client, "mum")
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    response = client.delete(f"{BASE_URL}/categories/nope", headers={**mum, "Accept-Language": "en"})
    assert response.json()["detail"] == messages.MESSAGES["de"]["category_not_found"]


def test_too_many_wrong_pins_counts_minutes():
    assert messages.plural("login_locked", 1) != messages.plural("login_locked", 2)
    assert "2" in messages.plural("login_locked", 2)


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_message_exists_in_both_languages_with_the_same_placeholders():
    de, en = messages.MESSAGES["de"], messages.MESSAGES["en"]
    assert de.keys() == en.keys()
    for key in de:
        assert placeholders(de[key]) == placeholders(en[key]), key


def test_german_texts_use_swiss_spelling():
    assert not [k for k, t in messages.MESSAGES["de"].items() if "ß" in t]


def test_plural_keys_come_in_pairs():
    keys = messages.MESSAGES["en"].keys()
    for key in keys:
        if key.endswith("_one"):
            assert re.sub("_one$", "_other", key) in keys, key
