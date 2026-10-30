"""Error messages in the caller's language (issue #50)."""

import ast
import re
import string
from pathlib import Path

from helpers import set_language, BASE_URL, add_transaction, create_account, register

from app import messages

WRONG = {"username": "nobody", "pin": "9999"}


def test_not_logged_in_follows_the_browser(client):
    german = client.get(f"{BASE_URL}/me", headers={"Accept-Language": "de-CH,de;q=0.9"})
    english = client.get(f"{BASE_URL}/me", headers={"Accept-Language": "en-US"})
    assert german.json()["detail"] == messages.MESSAGES["de"]["not_logged_in"]
    assert english.json()["detail"] == messages.MESSAGES["en"]["not_logged_in"]


def test_without_a_header_the_default_applies(client, monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "de")
    assert client.get(f"{BASE_URL}/me").json()["detail"] == messages.MESSAGES["de"]["not_logged_in"]


def test_the_persons_setting_beats_the_browser(client):
    mum = register(client, "mum")
    set_language(mum, "de")
    response = client.delete(f"{BASE_URL}/categories/nope", headers={**mum, "Accept-Language": "en"})
    assert response.json()["detail"] == messages.MESSAGES["de"]["category_not_found"]


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


APP = Path(__file__).resolve().parents[1] / "backend" / "app"


def name_of(call):
    return getattr(call.func, "id", getattr(call.func, "attr", ""))


def literal_details():
    """HTTPException(..., detail=<text>) written in the code instead of api_error()."""
    found = []
    for path in sorted(APP.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and name_of(node) == "HTTPException":
                for kw in node.keywords:
                    if kw.arg == "detail" and isinstance(kw.value, (ast.Constant, ast.JoinedStr)):
                        found.append(f"{path.name}:{node.lineno}")
    return found


def used_keys():
    keys = set()
    for path in sorted(APP.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            args = node.args[1:] if name_of(node) == "api_error" else node.args
            if name_of(node) in ("api_error", "text") and args and isinstance(args[0], ast.Constant):
                keys.add(args[0].value)
            if name_of(node) == "plural" and args and isinstance(args[0], ast.Constant):
                keys |= {args[0].value + "_one", args[0].value + "_other"}
    return keys


def test_no_error_text_outside_the_catalog():
    assert literal_details() == []


def test_every_used_key_is_in_the_catalog():
    assert used_keys() - messages.MESSAGES["en"].keys() == set()


def test_category_in_use_counts_in_german(client):
    mum = register(client, "mum")
    set_language(mum, "de")
    category = client.post(f"{BASE_URL}/categories", json={"name": "Velo", "type": "EXPENSE"}, headers=mum).json()
    account = create_account(client, mum)
    add_transaction(client, mum, account, category["id"], 10)
    response = client.put(f"{BASE_URL}/categories/{category['id']}", json={"type": "INCOME"}, headers=mum)
    assert response.json()["detail"] == "Verwendet von 1 Buchung; der Typ kann nicht mehr geändert werden"
    add_transaction(client, mum, account, category["id"], 5)
    response = client.delete(f"{BASE_URL}/categories/{category['id']}", headers=mum)
    assert response.json()["detail"] == "Verwendet von 2 Buchungen"
