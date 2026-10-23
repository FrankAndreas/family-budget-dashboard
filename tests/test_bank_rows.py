"""Imported bank lines are kept as bank rows, linked to their booking (bank import, part 2). Invented data only."""

from datetime import date

from alembic import command
from sqlalchemy import text
from test_bank_import import HOUSEHOLD, account, bank_file, line
from test_database import sqlite, without_link_checks
from test_import import upload

from app import database, database_setup, models
from helpers import BASE_URL, register

FILE = bank_file(
    line("Zahlung Muster", "-5.5", booked="2026-09-02", saldo="994.5"),
    line("Gutschrift Muster", "20", booked="2026-09-03", saldo="1014.5"),
)


def setup(client):
    mum = register(client, "mum")
    account_id = account(client, mum, "Household", HOUSEHOLD)
    return mum, account_id


def bank_rows():
    with database.SessionLocal() as db:
        return [
            (r.booked_on, r.valuta_on, r.text, r.amount, r.balance, r.transaction_id, r.account_id)
            for r in db.query(models.BankRow).order_by(models.BankRow.booked_on)
        ]


def bookings(client, headers, account_id):
    return client.get(f"{BASE_URL}/accounts/{account_id}/transactions", headers=headers).json()


def test_import_writes_bank_rows(client):
    mum, account_id = setup(client)
    assert upload(client, mum, FILE, name="export.csv", path="import").json()["imported"] == 2
    ids = {t["amount"]: t["id"] for t in bookings(client, mum, account_id)}
    assert bank_rows() == [
        (date(2026, 9, 2), date(2026, 9, 2), "Zahlung Muster", -5.5, 994.5, ids[-5.5], account_id),
        (date(2026, 9, 3), date(2026, 9, 3), "Gutschrift Muster", 20.0, 1014.5, ids[20.0], account_id),
    ]


def test_normal_import_writes_none(client):
    mum, _ = setup(client)
    content = "date,account,category,amount\n2026-09-01,Household,Groceries,5\n"
    assert upload(client, mum, content, path="import").json()["imported"] == 1
    assert bank_rows() == []


def test_linked_line_is_duplicate_on_reupload(client):
    mum, account_id = setup(client)
    upload(client, mum, FILE, name="export.csv", path="import")
    other = client.post(
        f"{BASE_URL}/transactions",
        json={
            "account_id": account_id,
            "category_id": bookings(client, mum, account_id)[0]["category_id"],
            "amount": 5.5,
        },
        headers=mum,
    ).json()
    with database.SessionLocal() as db:
        row = db.query(models.BankRow).filter(models.BankRow.amount == -5.5).one()
        created = row.transaction_id
        row.transaction_id = other["id"]
        db.commit()
    assert client.delete(f"{BASE_URL}/transactions/{created}", headers=mum).status_code == 200
    result = upload(client, mum, FILE, name="export.csv").json()
    assert [r["status"] for r in result["rows"]] == ["duplicate", "duplicate"]


def test_unlinked_line_is_duplicate_on_reupload(client):
    mum, account_id = setup(client)
    upload(client, mum, FILE, name="export.csv", path="import")
    for booking in bookings(client, mum, account_id):
        client.delete(f"{BASE_URL}/transactions/{booking['id']}", headers=mum)
    result = upload(client, mum, FILE, name="export.csv").json()
    assert [r["status"] for r in result["rows"]] == ["duplicate", "duplicate"]


def test_delete_booking_keeps_row(client):
    mum, account_id = setup(client)
    upload(client, mum, FILE, name="export.csv", path="import")
    first = bookings(client, mum, account_id)[0]["id"]
    assert client.delete(f"{BASE_URL}/transactions/{first}", headers=mum).status_code == 200
    rows = bank_rows()
    assert len(rows) == 2
    assert [r[5] for r in rows].count(None) == 1


def test_delete_account_with_rows(client):
    mum, account_id = setup(client)
    upload(client, mum, FILE, name="export.csv", path="import")
    assert client.delete(f"{BASE_URL}/accounts/{account_id}", headers=mum).status_code == 200
    assert bank_rows() == []


def test_migration_0013(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    database_setup.run(engine, command.downgrade, "0012")
    without_link_checks(
        engine,
        "INSERT INTO accounts (id, name, type) VALUES ('a1', 'Bank', 'BANK')",
        "INSERT INTO transactions (id, account_id, amount) VALUES ('t1', 'a1', -100)",
    )
    database_setup.setup(engine)
    with engine.connect() as conn:
        flags = conn.execute(text("SELECT receipt_expected, difference, difference_accepted FROM transactions")).one()
        assert tuple(flags) == (0, None, 0)
        assert conn.execute(text("SELECT count(*) FROM bank_rows")).scalar() == 0
