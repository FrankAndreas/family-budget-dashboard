"""The receipt mail inbox (issue #57): parents see the forwarded mails, release them to the AI, and book them."""

import json
from datetime import datetime, timedelta

import pytest

from helpers import BASE_URL, category_id, create_account, register, user_id
from mails import SECRET, post, with_pdf

from app import attachments, database, inbox, models, receipt_ai

INBOX = f"{BASE_URL}/inbox"
ANSWER = json.dumps(
    {
        "shop": "Migros",
        "date": "2026-10-20",
        "total": 3.5,
        "items": [{"name": "Brot", "amount": 3.5, "category": "Groceries"}],
    }
)


class Fake:
    def __init__(self):
        self.calls = 0

    def complete(self, content):
        self.calls += 1
        return ANSWER


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("INBOUND_SECRET", SECRET)


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setenv("INFOMANIAK_AI_TOKEN", "t")
    monkeypatch.setenv("INFOMANIAK_AI_PRODUCT_ID", "p")
    monkeypatch.delenv("RECEIPT_AI_READS_PER_HOUR", raising=False)
    fake = Fake()
    monkeypatch.setattr(receipt_ai, "client_for", lambda settings: fake)
    return fake


def parent(client, name, address=None):
    headers = register(client, name)
    if address:
        client.post(
            f"{BASE_URL}/users/{user_id(client, headers, name)}/emails", json={"address": address}, headers=headers
        )
    return headers


def received(client, sender="dad@example.ch", **extra):
    response = post(client, with_pdf(sender, **extra))
    assert response.status_code == 200, response.text
    return response.json()["id"]


def listing(client, headers):
    return client.get(INBOX, headers=headers).json()


def release(client, headers, entry_id):
    return client.post(f"{INBOX}/{entry_id}/release", headers=headers)


def book(client, headers, account, attachment_id):
    groceries = category_id(client, "Groceries")
    return client.post(
        f"{BASE_URL}/transactions",
        json={
            "account_id": account,
            "items": [{"name": "Brot", "amount": 3.5, "category_id": groceries}],
            "attachment_ids": [attachment_id],
        },
        headers=headers,
    )


def test_parents_see_the_inbox_children_dont(client):
    mum = parent(client, "mum")
    parent(client, "dad", "dad@example.ch")
    kid = register(client, "kid", role="CHILD", by=mum)
    entry = received(client)
    assert [e["id"] for e in listing(client, mum)] == [entry]
    response = client.get(INBOX, headers=kid)
    assert response.status_code == 403 and response.json()["detail"] == "Only parents can see the receipt inbox"
    assert release(client, kid, entry).status_code == 403
    assert client.delete(f"{INBOX}/{entry}", headers=kid).status_code == 403


def test_listing_shows_headers_only(client):
    mum = parent(client, "mum")
    dad = parent(client, "dad", "dad@example.ch")
    first = received(client, message_id="<1@example.ch>")
    second = received(client, message_id="<2@example.ch>", subject="WG: Galaxus")
    rows = listing(client, mum)
    assert [r["id"] for r in rows] == [second, first]
    row = rows[0]
    assert row["person_id"] == user_id(client, dad, "dad") and row["person_name"] == "dad"
    assert row["from_addr"] == "dad@example.ch" and row["subject"] == "WG: Galaxus"
    assert row["attachment_names"] == ["beleg.pdf"] and row["size"] > 0
    assert set(row) >= {"sent_at", "received_at", "suggested_account_id"}


def test_delete(client):
    mum = parent(client, "mum", "mum@example.ch")
    entry = received(client, "mum@example.ch")
    assert client.delete(f"{INBOX}/{entry}", headers=mum).json() == {"deleted": entry}
    assert listing(client, mum) == [] and not (inbox.inbox_dir() / entry).exists()
    assert client.delete(f"{INBOX}/{entry}", headers=mum).status_code == 404


def test_release_reads_with_the_ai(client, ai, monkeypatch):
    monkeypatch.setenv("RECEIPT_AI_READS_PER_HOUR", "1")
    mum = parent(client, "mum", "mum@example.ch")
    dad = parent(client, "dad")
    entry = received(client, "mum@example.ch")
    response = release(client, mum, entry)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [i["name"] for i in body["draft"]["items"]] == ["Brot"] and ai.calls == 1
    with database.SessionLocal() as db:
        attachment = db.query(models.Attachment).filter(models.Attachment.id == body["attachment_id"]).one()
        assert attachment.transaction_id is None and attachment.content_type == "message/rfc822"
        assert attachment.owner_id == user_id(client, mum, "mum")
    # The reading counts for the parent who released it
    assert release(client, mum, entry).status_code == 429
    assert release(client, dad, entry).status_code == 200


def test_release_without_ai(client, monkeypatch):
    monkeypatch.delenv("INFOMANIAK_AI_TOKEN", raising=False)
    called = []
    monkeypatch.setattr(receipt_ai, "client_for", lambda settings: called.append(1))
    mum = parent(client, "mum", "mum@example.ch")
    response = release(client, mum, received(client, "mum@example.ch"))
    assert response.status_code == 200, response.text
    assert response.json()["draft"] is None and response.json()["attachment_id"]
    assert called == []


def test_booking_marks_the_entry_booked(client, ai):
    mum = parent(client, "mum", "mum@example.ch")
    account = create_account(client, mum, "Migros")
    entry = received(client, "mum@example.ch")
    attachment_id = release(client, mum, entry).json()["attachment_id"]
    booked = book(client, mum, account, attachment_id)
    assert booked.status_code == 200, booked.text
    assert [a["content_type"] for a in booked.json()["attachments"]] == ["message/rfc822"]
    assert listing(client, mum) == [] and not (inbox.inbox_dir() / entry).exists()
    # The same mail forwarded again is a duplicate, not a new entry
    assert post(client, with_pdf("mum@example.ch")).json() == {"status": "duplicate"}


def test_release_twice_and_two_parents(client, ai):
    mum = parent(client, "mum", "mum@example.ch")
    dad = parent(client, "dad")
    account = create_account(client, mum, "Migros")
    entry = received(client, "mum@example.ch")
    mine = release(client, mum, entry).json()["attachment_id"]
    again = release(client, mum, entry).json()["attachment_id"]
    dads = release(client, dad, entry).json()["attachment_id"]
    assert len({mine, again, dads}) == 3
    # Booking the first release (not the latest) still clears the entry
    assert book(client, mum, account, mine).status_code == 200
    assert listing(client, mum) == []
    with database.SessionLocal() as db:
        old = db.query(models.Attachment).filter(models.Attachment.id == dads).one()
        old.created_at = datetime.utcnow() - timedelta(hours=25)
        db.commit()
        attachments.sweep(db)
        assert db.query(models.Attachment).filter(models.Attachment.id == dads).first() is None


def test_account_suggestion(client, ai):
    mum = parent(client, "mum")
    dad = parent(client, "dad", "dad@example.ch")
    dad_id = user_id(client, dad, "dad")
    bank = create_account(client, dad, "A Bank")
    card = create_account(client, dad, "Kreditkarte")
    received(client, message_id="<1@example.ch>")
    # No receipt booked yet: the forwarder's first account by name
    assert listing(client, dad)[0]["suggested_account_id"] == bank
    first = received(client, message_id="<2@example.ch>")
    assert book(client, dad, card, release(client, dad, first).json()["attachment_id"]).status_code == 200
    assert listing(client, dad)[0]["suggested_account_id"] == card
    # Mum may not write to dad's accounts (not shared): no suggestion for her
    assert listing(client, mum)[0]["suggested_account_id"] is None
    del dad_id


def test_forwarder_removed_keeps_the_entry(client):
    mum = parent(client, "mum")
    parent(client, "dad", "dad@example.ch")
    create_account(client, mum)
    entry = received(client)
    assert client.delete(f"{BASE_URL}/users/{user_id(client, mum, 'dad')}", headers=mum).status_code == 200
    [row] = listing(client, mum)
    assert row["id"] == entry and row["person_id"] is None and row["suggested_account_id"] is None


def test_sweep_after_30_days(client):
    mum = parent(client, "mum", "mum@example.ch")
    old = received(client, "mum@example.ch", message_id="<old@example.ch>")
    recent = received(client, "mum@example.ch", message_id="<recent@example.ch>")
    with database.SessionLocal() as db:
        ages = {old: 31, recent: 29}
        for entry in db.query(models.InboxMail):
            entry.received_at = datetime.utcnow() - timedelta(days=ages[entry.id])
        db.commit()
        assert inbox.sweep(db) == 1
    assert [r["id"] for r in listing(client, mum)] == [recent]
    assert not (inbox.inbox_dir() / old).exists() and (inbox.inbox_dir() / recent).exists()
