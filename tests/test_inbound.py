"""Receiving forwarded receipt mails (issue #57): only the headers are read, the mail waits unopened."""

import logging

import pytest

from helpers import BASE_URL, register, user_id
from mails import SECRET, forwarded, post, with_pdf

from app import database, inbox, models


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("INBOUND_SECRET", SECRET)


def registered(client, name="mum", address="mum@example.ch"):
    headers = register(client, name)
    client.post(f"{BASE_URL}/users/{user_id(client, headers, name)}/emails", json={"address": address}, headers=headers)
    return headers


def entries():
    with database.SessionLocal() as db:
        return db.query(models.InboxMail).all()


def test_off_without_secret(client, monkeypatch):
    monkeypatch.delenv("INBOUND_SECRET")
    assert post(client, with_pdf()).status_code == 503


def test_wrong_secret(client):
    registered(client)
    assert post(client, with_pdf(), secret="wrong").status_code == 401
    assert post(client, with_pdf(), secret=None).status_code == 401
    assert entries() == []


def test_too_big(client):
    registered(client)
    raw = forwarded(attachments=[("big.pdf", b"%PDF-" + b"x" * (10 * 1024 * 1024), "application", "pdf")])
    assert post(client, raw).status_code == 413
    assert entries() == []


def test_unknown_sender_is_refused(client):
    registered(client)
    response = post(client, with_pdf("stranger@example.ch"))
    assert response.status_code == 403
    assert entries() == [] and not any(inbox.inbox_dir().iterdir())


def test_inactive_person_is_refused(client):
    registered(client)
    with database.SessionLocal() as db:
        db.query(models.User).filter(models.User.username == "mum").one().is_active = False
        db.commit()
    assert post(client, with_pdf()).status_code == 403


def test_registered_sender_lands_in_the_inbox(client):
    mum = registered(client)
    raw = with_pdf('"Mum" <MUM@Example.ch>')
    response = post(client, raw)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "stored"
    [entry] = entries()
    assert entry.id == response.json()["id"]
    assert entry.person_id == user_id(client, mum, "mum")
    assert entry.from_addr == "mum@example.ch"
    assert entry.subject == "WG: Ihre Bestellung"
    assert entry.attachment_names == ["beleg.pdf"]
    assert entry.size == len(raw) and entry.sent_at is not None
    assert (inbox.inbox_dir() / entry.id).read_bytes() == raw


def test_two_from_addresses_are_refused(client):
    registered(client)
    registered(client, "dad", "dad@example.ch")
    assert post(client, with_pdf("mum@example.ch, dad@example.ch")).status_code == 403


def test_duplicate_message_id(client):
    registered(client)
    assert post(client, with_pdf()).json()["status"] == "stored"
    assert post(client, with_pdf()).json() == {"status": "duplicate"}
    assert len(entries()) == 1


def test_no_message_id_is_still_deduplicated(client):
    registered(client)
    raw = with_pdf(message_id=None)
    assert post(client, raw).json()["status"] == "stored"
    assert post(client, raw).json() == {"status": "duplicate"}
    assert entries()[0].message_id.startswith("sha256:")


def test_malformed_headers(client):
    registered(client)
    raw = (
        b"From: mum@example.ch\r\nSubject: Quittung \xff\xfe kaputt\r\nDate: not a date\r\n"
        b"Message-ID: <broken@example.ch>\r\n\r\nTotal 12.50\r\n"
    )
    response = post(client, raw)
    assert response.status_code == 200, response.text
    [entry] = entries()
    assert entry.subject and entry.sent_at is None


def test_nothing_is_decoded_on_arrival(client, monkeypatch):
    from app import receipt_files

    def refuse(*args, **kwargs):
        raise AssertionError("decoded on arrival")

    monkeypatch.setattr(receipt_files, "ai_content", refuse)
    monkeypatch.setattr("PIL.Image.open", refuse)
    registered(client)
    raw = forwarded(attachments=[("foto.png", b"\x89PNG\r\n\x1a\nbroken", "image", "png")])
    assert post(client, raw).status_code == 200
    assert entries()[0].attachment_names == ["foto.png"]


def test_secret_never_in_response_or_log(client, caplog):
    registered(client)
    with caplog.at_level(logging.DEBUG):
        responses = [
            post(client, with_pdf()),
            post(client, with_pdf(), secret="wrong"),
            post(client, with_pdf("x@y.ch")),
        ]
    for text in [r.text for r in responses] + [caplog.text]:
        assert SECRET not in text
