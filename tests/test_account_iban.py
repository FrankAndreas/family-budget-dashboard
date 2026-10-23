"""IBAN on accounts: a bank statement's lines find their account by it (bank import, part 1)."""

import csv
import io
import zipfile

from alembic import command
from sqlalchemy import text
from test_database import sqlite, without_link_checks

from app import database_setup
from helpers import BASE_URL, create_account, register

ACCOUNTS = f"{BASE_URL}/accounts"
IBAN = "CH9300762011623852957"


def add(client, headers, iban, name="Bank"):
    return client.post(ACCOUNTS, json={"name": name, "type": "BANK", "iban": iban}, headers=headers)


def test_parent_sets_iban(client):
    mum = register(client, "mum")
    response = add(client, mum, "ch93 0076 2011 6238 5295 7")
    assert response.status_code == 200, response.text
    assert response.json()["iban"] == IBAN
    assert client.get(ACCOUNTS, headers=mum).json()[0]["iban"] == IBAN


def test_update_iban_and_clear(client):
    mum = register(client, "mum")
    account = create_account(client, mum)
    response = client.put(f"{ACCOUNTS}/{account}", json={"iban": "CH93 0076 2011 6238 5295 7"}, headers=mum)
    assert response.json()["iban"] == IBAN
    response = client.put(f"{ACCOUNTS}/{account}", json={"iban": ""}, headers=mum)
    assert response.status_code == 200
    assert response.json()["iban"] is None


def test_invalid_iban(client):
    mum = register(client, "mum")
    for iban in ("CH93 0076 2011 6238 5295 8", "CH93", "9300762011623852957", "CH93 0076 2011 6238 5295 7!"):
        response = add(client, mum, iban)
        assert response.status_code == 400, iban
        assert response.json()["detail"] == "That is not a valid IBAN"
    account = create_account(client, mum)
    assert client.put(f"{ACCOUNTS}/{account}", json={"iban": "CH00 1234"}, headers=mum).status_code == 400


def test_iban_unique(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    assert add(client, mum, IBAN).status_code == 200
    response = add(client, dad, "CH93 0076 2011 6238 5295 7", "Dad bank")
    assert response.status_code == 400
    assert response.json()["detail"] == "Another account already has this IBAN"
    other = create_account(client, mum, "Savings")
    assert client.put(f"{ACCOUNTS}/{other}", json={"iban": IBAN}, headers=mum).status_code == 400


def test_same_account_keeps_its_iban(client):
    mum = register(client, "mum")
    account = add(client, mum, IBAN).json()["id"]
    response = client.put(f"{ACCOUNTS}/{account}", json={"name": "Raiffeisen", "iban": IBAN}, headers=mum)
    assert response.status_code == 200, response.text


def test_child_cannot_set_iban(client):
    mum = register(client, "mum")
    teen = register(client, "teen", role="CHILD", by=mum)
    response = add(client, teen, IBAN, "Teen bank")
    assert response.status_code == 403
    assert response.json()["detail"] == "Only parents can set an IBAN"
    account = create_account(client, teen, "Teen bank")
    assert client.put(f"{ACCOUNTS}/{account}", json={"iban": IBAN}, headers=teen).status_code == 403
    assert client.put(f"{ACCOUNTS}/{account}", json={"name": "Teen"}, headers=teen).status_code == 200


def test_export_has_iban(client):
    mum = register(client, "mum")
    add(client, mum, IBAN)
    response = client.get(f"{BASE_URL}/export/analysis.zip", headers=mum)
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    rows = list(csv.DictReader(io.StringIO(archive.read("accounts.csv").decode("utf-8"))))
    assert rows[0]["iban"] == IBAN


def test_migration_0012(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    database_setup.run(engine, command.downgrade, "0011")
    without_link_checks(
        engine,
        "INSERT INTO accounts (id, name, type) VALUES ('a1', 'Bank', 'BANK')",
        "INSERT INTO import_rules (id, text) VALUES ('r1', 'Coop')",
    )
    database_setup.setup(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT iban FROM accounts")).scalar() is None
        assert conn.execute(text("SELECT receipt_expected FROM import_rules")).scalar() == 0
