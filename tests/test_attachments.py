"""Receipts kept with their booking (issue #56): photos, PDFs and e-mails, stored under an id, served only to people
who may see the booking, deleted with it."""

import io
import os
from datetime import datetime, timedelta

from PIL import Image

from helpers import BASE_URL, add_transaction, category_id, create_account, register

from app import attachments, database, models

PNG_BYTES = io.BytesIO()
Image.new("RGB", (4, 4), "white").save(PNG_BYTES, format="PNG")
PNG = PNG_BYTES.getvalue()
PDF = b"%PDF-1.4\n%fake but starts like a PDF\n"
EML = b"From: shop@example.ch\r\nSubject: Ihre Quittung\r\nContent-Type: text/html\r\n\r\n<script>alert(1)</script>CHF 12.50\r\n"


def booking(client, headers):
    account = create_account(client, headers)
    return add_transaction(client, headers, account, category_id(client, "Groceries"), 12.5).json()


def upload(client, headers, transaction_id, name, data):
    return client.post(
        f"{BASE_URL}/transactions/{transaction_id}/attachments", files={"file": (name, data)}, headers=headers
    )


def test_store_and_fetch_a_photo(client, attachments_dir):
    mum = register(client, "mum")
    tx = booking(client, mum)
    stored = upload(client, mum, tx["id"], "beleg.png", PNG).json()
    assert stored["content_type"] == "image/png" and stored["size"] == len(PNG) and stored["filename"] == "beleg.png"
    # Stored under its id, never under the uploaded name
    assert os.listdir(attachments_dir) == [stored["id"]]
    response = client.get(f"{BASE_URL}/attachments/{stored['id']}", headers=mum)
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    listed = client.get(f"{BASE_URL}/accounts/{tx['account_id']}/transactions", headers=mum).json()
    assert [a["id"] for a in listed[0]["attachments"]] == [stored["id"]]


def test_the_type_comes_from_the_content(client):
    mum = register(client, "mum")
    tx = booking(client, mum)
    response = upload(client, mum, tx["id"], "beleg.jpg", b"not an image at all")
    assert response.status_code == 400 and response.json()["detail"] == "This file can't be read"
    assert upload(client, mum, tx["id"], "quittung.pdf", PDF).json()["content_type"] == "application/pdf"


def test_an_email_is_only_downloaded(client):
    mum = register(client, "mum")
    stored = upload(client, mum, booking(client, mum)["id"], "quittung.eml", EML).json()
    assert stored["content_type"] == "message/rfc822"
    response = client.get(f"{BASE_URL}/attachments/{stored['id']}", headers=mum)
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-type"].startswith("message/rfc822")


def test_too_large(client, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_BYTES", 100)
    mum = register(client, "mum")
    response = upload(client, mum, booking(client, mum)["id"], "beleg.png", PNG + b"x" * 100)
    assert response.status_code == 400 and response.json()["detail"] == "The file is larger than 10 MB"


def test_others_cannot_see_or_delete_it(client):
    mum, dad = register(client, "mum"), register(client, "dad")
    stored = upload(client, mum, booking(client, mum)["id"], "beleg.png", PNG).json()
    assert client.get(f"{BASE_URL}/attachments/{stored['id']}", headers=dad).status_code == 404
    assert client.delete(f"{BASE_URL}/attachments/{stored['id']}", headers=dad).status_code == 404
    assert upload(client, dad, "nope", "x.png", PNG).status_code == 404


def test_delete_an_attachment(client, attachments_dir):
    mum = register(client, "mum")
    stored = upload(client, mum, booking(client, mum)["id"], "beleg.png", PNG).json()
    assert client.delete(f"{BASE_URL}/attachments/{stored['id']}", headers=mum).status_code == 200
    assert os.listdir(attachments_dir) == []


def pending(owner_name, data=PNG, age=timedelta(0)):
    with database.SessionLocal() as db:
        owner = db.query(models.User).filter(models.User.username == owner_name).one()
        attachment = attachments.store(db, owner, "beleg.png", data, None)
        attachment.created_at = datetime.utcnow() - age
        db.commit()
        return attachment.id


def test_pending_attachment_is_linked_when_booking(client):
    mum = register(client, "mum")
    attachment_id = pending("mum")
    response = add_transaction(
        client, mum, create_account(client, mum), category_id(client, "Groceries"), 5, attachment_ids=[attachment_id]
    )
    assert [a["id"] for a in response.json()["attachments"]] == [attachment_id]


def test_someone_elses_pending_attachment_is_refused(client):
    mum = register(client, "mum")
    register(client, "dad")
    attachment_id = pending("dad")
    response = add_transaction(
        client, mum, create_account(client, mum), category_id(client, "Groceries"), 5, attachment_ids=[attachment_id]
    )
    assert response.status_code == 400 and response.json()["detail"] == "Attachment not found"


def test_deleting_the_booking_deletes_the_file(client, attachments_dir):
    mum = register(client, "mum")
    tx = booking(client, mum)
    upload(client, mum, tx["id"], "beleg.png", PNG)
    client.delete(f"{BASE_URL}/transactions/{tx['id']}", headers=mum)
    assert os.listdir(attachments_dir) == []


def test_deleting_an_account_and_sweep(client, attachments_dir):
    mum = register(client, "mum")
    tx = booking(client, mum)
    upload(client, mum, tx["id"], "beleg.png", PNG)
    assert client.delete(f"{BASE_URL}/accounts/{tx['account_id']}", headers=mum).status_code == 200
    with database.SessionLocal() as db:
        assert db.query(models.Attachment).count() == 0
        # The bulk delete leaves the file; the sweep removes files without a row (once they are an hour old)
        age(attachments_dir, hours=2)
        assert attachments.sweep(db) == 1
    assert os.listdir(attachments_dir) == []


def test_sweep_removes_old_pending_attachments(client, attachments_dir):
    register(client, "mum")
    old, recent = pending("mum", age=timedelta(hours=25)), pending("mum", age=timedelta(hours=23))
    with database.SessionLocal() as db:
        assert attachments.sweep(db) == 1
        assert [a.id for a in db.query(models.Attachment)] == [recent]
    assert os.listdir(attachments_dir) == [recent]
    del old


def test_removing_the_uploader_keeps_the_receipt_on_someone_elses_booking(client):
    from helpers import admin_headers, user_id

    admin = admin_headers(client)
    mum = register(client, "mum")
    # Admin shares their finances with mum ("view and manage"), so mum can attach to admin's booking
    client.put(f"{BASE_URL}/shares/{user_id(client, admin, 'mum')}", json={"level": "EDIT"}, headers=admin)
    tx = booking(client, admin)
    stored = upload(client, mum, tx["id"], "beleg.png", PNG).json()
    assert "id" in stored, stored
    removed = client.request(
        "DELETE", f"{BASE_URL}/users/{user_id(client, admin, 'mum')}", json={"items": []}, headers=admin
    )
    assert removed.status_code == 200
    listed = client.get(f"{BASE_URL}/accounts/{tx['account_id']}/transactions", headers=admin).json()
    assert [a["id"] for a in listed[0]["attachments"]] == [stored["id"]]
    assert client.get(f"{BASE_URL}/attachments/{stored['id']}", headers=admin).content == PNG


def test_upload_a_pending_attachment_for_a_new_booking(client, attachments_dir):
    """Without the AI, a new receipt's file is uploaded first and linked when booking."""
    mum = register(client, "mum")
    response = client.post(f"{BASE_URL}/attachments", files={"file": ("beleg.png", PNG)}, headers=mum)
    assert response.status_code == 200, response.text
    attachment_id = response.json()["id"]
    assert response.json()["content_type"] == "image/png"
    booked = add_transaction(
        client, mum, create_account(client, mum), category_id(client, "Groceries"), 5, attachment_ids=[attachment_id]
    )
    assert [a["id"] for a in booked.json()["attachments"]] == [attachment_id]
    assert os.listdir(attachments_dir) == [attachment_id]


def test_upload_a_pending_attachment_checks_the_file(client):
    mum = register(client, "mum")
    response = client.post(f"{BASE_URL}/attachments", files={"file": ("beleg.txt", b"hello")}, headers=mum)
    assert response.status_code == 400 and response.json()["detail"] == "This file can't be read"


def age(folder, hours):
    """Make the files in the folder look older, as if written some hours ago."""
    then = (datetime.now() - timedelta(hours=hours)).timestamp()
    for path in folder.iterdir():
        if path.is_file():
            os.utime(path, (then, then))


def test_sweep_keeps_a_fresh_file_without_row(client, attachments_dir):
    """A file is written a moment before its row is committed; the sweep must not take it in between (issue #75)."""
    with database.SessionLocal() as db:
        attachments.directory()
        (attachments_dir / "being-stored").write_bytes(PNG)
        assert attachments.sweep(db) == 0
        assert os.listdir(attachments_dir) == ["being-stored"]
        age(attachments_dir, hours=2)
        assert attachments.sweep(db) == 1
    assert os.listdir(attachments_dir) == []
