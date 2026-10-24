"""Receipts photographed on the phone wait in the inbox until a parent books them (receipt scan). Invented images."""

import os
import time
from datetime import datetime, timedelta

from files import image_png, pdf_with_text

from app import attachments, database, inbox, models
from helpers import BASE_URL, category_id, create_account, register

PHOTOS = f"{BASE_URL}/inbox/photos"


def scan(client, headers, data=None, name="scan.jpg"):
    return client.post(PHOTOS, files={"file": (name, data or image_png(), "image/jpeg")}, headers=headers)


def scanned(client, headers, text="MIGROS 12.50"):
    response = scan(client, headers, image_png(text))
    assert response.status_code == 200, response.text
    return response.json()


def photos(client, headers):
    response = client.get(PHOTOS, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def items(client, amount=3.5):
    return [{"name": "Brot", "amount": amount, "category_id": category_id(client, "Groceries")}]


def opened(client, headers, photo_id):
    response = client.post(f"{PHOTOS}/{photo_id}/open", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_parents_scan_children_dont(client):
    mum = register(client, "mum")
    photo = scanned(client, mum)
    assert photo["read_state"] == "waiting"
    assert photo["person_name"] == "mum"
    teen = register(client, "teen", role="CHILD", by=mum)
    assert scan(client, teen).status_code == 403
    assert client.get(PHOTOS, headers=teen).status_code == 403


def test_only_images(client):
    mum = register(client, "mum")
    assert scan(client, mum, pdf_with_text(["x"]), name="scan.pdf").status_code == 400
    too_big = image_png() + b"\0" * (attachments.MAX_BYTES + 1)
    assert scan(client, mum, too_big).status_code == 400
    assert photos(client, mum) == []


def test_listing_oldest_first_and_both_parents_see_it(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    first = scanned(client, mum, "ONE")
    second = scanned(client, mum, "TWO")
    assert [p["id"] for p in photos(client, mum)] == [first["id"], second["id"]]
    assert [p["id"] for p in photos(client, dad)] == [first["id"], second["id"]]


def test_delete_removes_file(client):
    mum = register(client, "mum")
    photo = scanned(client, mum)
    assert (inbox.inbox_dir() / photo["id"]).exists()
    assert client.delete(f"{PHOTOS}/{photo['id']}", headers=mum).json() == {"deleted": photo["id"]}
    assert photos(client, mum) == []
    assert not (inbox.inbox_dir() / photo["id"]).exists()
    assert client.delete(f"{PHOTOS}/{photo['id']}", headers=mum).status_code == 404


def test_open_without_ai_then_book_marks_photo_booked(client):
    mum = register(client, "mum")
    account = create_account(client, mum)
    photo = scanned(client, mum)
    result = opened(client, mum, photo["id"])
    assert result["draft"] is None
    assert result["attachment"]["content_type"] == "image/png"
    response = client.post(
        f"{BASE_URL}/transactions",
        json={"account_id": account, "items": items(client), "attachment_ids": [result["attachment_id"]]},
        headers=mum,
    )
    assert response.status_code == 200, response.text
    assert photos(client, mum) == []
    with database.SessionLocal() as db:
        assert db.get(models.InboxPhoto, photo["id"]).booked_at is not None
    assert not (inbox.inbox_dir() / photo["id"]).exists()


def test_booking_onto_existing_booking_marks_photo_booked(client):
    mum = register(client, "mum")
    account = create_account(client, mum)
    existing = client.post(
        f"{BASE_URL}/transactions",
        json={"account_id": account, "category_id": category_id(client, "Groceries"), "amount": 3.5},
        headers=mum,
    ).json()["id"]
    photo = scanned(client, mum)
    result = opened(client, mum, photo["id"])
    response = client.put(
        f"{BASE_URL}/transactions/{existing}",
        json={"items": items(client), "attachment_ids": [result["attachment_id"]]},
        headers=mum,
    )
    assert response.status_code == 200, response.text
    assert photos(client, mum) == []


def test_sweep_keeps_photos(client):
    mum = register(client, "mum")
    photo = scanned(client, mum)
    path = inbox.inbox_dir() / photo["id"]
    two_hours_ago = time.time() - 7200
    os.utime(path, (two_hours_ago, two_hours_ago))
    with database.SessionLocal() as db:
        inbox.sweep(db, now=datetime.utcnow() + timedelta(days=40))
    assert path.exists()
    assert [p["id"] for p in photos(client, mum)] == [photo["id"]]


def test_suggested_account(client):
    mum = register(client, "mum")
    create_account(client, mum, "Cash")
    bank = create_account(client, mum, "Mum bank")
    client.post(f"{BASE_URL}/transactions", json={"account_id": bank, "items": items(client)}, headers=mum)
    assert scanned(client, mum)["suggested_account_id"] == bank
