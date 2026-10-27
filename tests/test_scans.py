"""Receipts photographed on the phone wait in the inbox until a parent books them (receipt scan). Invented images."""

import json
import os
import time
from datetime import datetime, timedelta

import pytest
from files import image_png, pdf_with_text

from app import attachments, database, inbox, models, receipt_ai, scans
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


# Reading in the background (Task 2): a fake AI answers with a fixed receipt
ANSWER = json.dumps({"shop": "Migros", "date": "2026-10-20", "total": 3.5, "items": [{"name": "Brot", "amount": 3.5}]})


class Fake:
    def __init__(self):
        self.calls = 0
        self.down = False
        self.questions = []

    def complete(self, content):
        self.calls += 1
        self.questions.append(content[0]["text"])
        if self.down:
            raise receipt_ai.AiUnavailable("down")
        return ANSWER


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setenv("INFOMANIAK_AI_TOKEN", "t")
    monkeypatch.setenv("INFOMANIAK_AI_PRODUCT_ID", "p")
    monkeypatch.delenv("RECEIPT_AI_READS_PER_HOUR", raising=False)
    fake = Fake()
    monkeypatch.setattr(receipt_ai, "client_for", lambda settings: fake)
    return fake


def states(client, headers):
    return [p["read_state"] for p in photos(client, headers)]


def test_upload_reads_in_background(client, ai):
    mum = register(client, "mum")
    photo = scanned(client, mum)
    [listed] = photos(client, mum)
    assert (listed["read_state"], listed["shop"], listed["total"]) == ("read", "Migros", 3.5)
    assert ai.calls == 1
    assert opened(client, mum, photo["id"])["draft"]["shop"] == "Migros"
    assert ai.calls == 1


def test_reads_in_takers_language(client, ai):
    mum = register(client, "mum")
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    scanned(client, mum)
    german = receipt_ai.PROMPTS["de"].split("{")[0][:40]
    assert ai.questions[0].startswith(german)


def test_ai_down_marks_failed_and_open_still_works(client, ai):
    mum = register(client, "mum")
    ai.down = True
    photo = scanned(client, mum)
    assert states(client, mum) == ["failed"]
    result = opened(client, mum, photo["id"])
    assert ai.calls == 2
    assert result["draft"] is None and result["attachment_id"]
    ai.down = False
    assert opened(client, mum, photo["id"])["draft"]["shop"] == "Migros"
    assert states(client, mum) == ["read"]


def test_over_the_limit_waits(client, ai, monkeypatch):
    monkeypatch.setenv("RECEIPT_AI_READS_PER_HOUR", "1")
    mum = register(client, "mum")
    dad = register(client, "dad")
    scanned(client, mum, "ONE")
    second = scanned(client, mum, "TWO")
    assert states(client, mum) == ["read", "waiting"]
    assert scans.read_waiting() == 0
    # Opening it uses the opener's reads
    assert opened(client, dad, second["id"])["draft"]["shop"] == "Migros"
    assert states(client, mum) == ["read", "read"]


def test_resume_after_restart(client, ai):
    mum = register(client, "mum")
    ai.down = True
    photo = scanned(client, mum)
    ai.down = False
    with database.SessionLocal() as db:
        db.get(models.InboxPhoto, photo["id"]).read_state = "reading"
        db.commit()
        scans.resume(db)
    assert scans.read_waiting() == 1
    assert states(client, mum) == ["read"]


def test_receipts_read_unchanged(client, ai):
    mum = register(client, "mum")
    response = client.post(f"{BASE_URL}/receipts/read", files={"file": ("beleg.png", image_png())}, headers=mum)
    assert response.status_code == 200, response.text
    assert response.json()["draft"]["shop"] == "Migros" and response.json()["attachment_id"]
    with database.SessionLocal() as db:
        assert db.query(models.ReceiptRead).count() == 1


# The four minors from the receipt-scan review
def test_unexpected_error_marks_failed_not_reading(client, ai, monkeypatch):
    mum = register(client, "mum")

    def broken(*args, **kwargs):
        raise RuntimeError("disk")

    monkeypatch.setattr(receipt_ai, "ai_draft", broken)
    photo = scanned(client, mum)
    assert states(client, mum) == ["failed"]
    # Opening still works: the form gets the photo without a draft
    assert opened(client, mum, photo["id"])["draft"] is None


def test_receipt_file_prepared_once(client, ai, monkeypatch):
    from app import receipt_files

    calls = []
    real = receipt_files.ai_content
    monkeypatch.setattr(receipt_files, "ai_content", lambda *args: calls.append(1) or real(*args))
    mum = register(client, "mum")
    response = client.post(f"{BASE_URL}/receipts/read", files={"file": ("beleg.png", image_png())}, headers=mum)
    assert response.status_code == 200, response.text
    assert len(calls) == 1


def test_opening_again_reuses_the_attachment(client):
    mum = register(client, "mum")
    photo = scanned(client, mum)
    first = opened(client, mum, photo["id"])["attachment_id"]
    assert opened(client, mum, photo["id"])["attachment_id"] == first
    with database.SessionLocal() as db:
        assert db.query(models.Attachment).count() == 1


def test_photo_booked_once_only(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    mum_account = create_account(client, mum, "Mum bank")
    dad_account = create_account(client, dad, "Dad bank")
    photo = scanned(client, mum)
    mine, theirs = opened(client, mum, photo["id"]), opened(client, dad, photo["id"])

    def book(headers, account, result):
        return client.post(
            f"{BASE_URL}/transactions",
            json={"account_id": account, "items": items(client), "attachment_ids": [result["attachment_id"]]},
            headers=headers,
        )

    assert book(mum, mum_account, mine).status_code == 200
    response = book(dad, dad_account, theirs)
    assert response.status_code == 409
    assert response.json()["detail"] == "This receipt has already been booked"
    with database.SessionLocal() as db:
        assert db.query(models.Transaction).count() == 1


def test_photo_not_found_message(client):
    mum = register(client, "mum")
    response = client.post(f"{PHOTOS}/nope/open", headers=mum)
    assert (response.status_code, response.json()["detail"]) == (404, "Photo not found in the inbox")


def test_scanned_without_ai_is_never_read(client, ai):
    """A pile scanned with "Read with AI" off (2026-10-24 review): the photos never go to the AI, not even on opening."""
    mum = register(client, "mum")
    response = client.post(
        PHOTOS, files={"file": ("scan.jpg", image_png(), "image/jpeg")}, data={"ai": "0"}, headers=mum
    )
    assert response.status_code == 200, response.text
    assert response.json()["read_state"] == "manual"
    assert scans.read_waiting() == 0
    result = opened(client, mum, response.json()["id"])
    assert result["draft"] is None and result["attachment_id"]
    assert ai.calls == 0
    assert states(client, mum) == ["manual"]


def test_suggested_account_prefers_a_bank_account(client):
    """Nothing booked from a receipt yet: a bank account, not the cash one that comes first by name."""
    mum = register(client, "mum")
    client.post(f"{BASE_URL}/accounts", json={"name": "Bargeld", "type": "CASH"}, headers=mum)
    bank = create_account(client, mum, "Zürcher Bank")
    assert scanned(client, mum)["suggested_account_id"] == bank


# The list of scanned receipts (issue #90): a thumbnail per photo, and likely duplicates flagged


def test_thumbnail(client):
    from PIL import Image
    import io

    mum = register(client, "mum")
    photo = scanned(client, mum)
    response = client.get(f"{PHOTOS}/{photo['id']}/thumbnail", headers=mum)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert max(Image.open(io.BytesIO(response.content)).size) == scans.THUMBNAIL_SIDE
    teen = register(client, "teen", role="CHILD", by=mum)
    assert client.get(f"{PHOTOS}/{photo['id']}/thumbnail", headers=teen).status_code == 403
    assert client.get(f"{PHOTOS}/no-such-photo/thumbnail", headers=mum).status_code == 404


def test_same_photo_twice_is_a_likely_duplicate(client):
    mum = register(client, "mum")
    data = image_png("MIGROS 12.50")
    first = scan(client, mum, data).json()
    second = scan(client, mum, data).json()
    listed = {p["id"]: p["duplicate"] for p in photos(client, mum)}
    # The earlier one is the original; only the later one is flagged
    assert listed == {first["id"]: False, second["id"]: True}


def test_same_shop_total_and_date_is_a_likely_duplicate(client, ai):
    mum = register(client, "mum")
    first = scanned(client, mum, "ONE")
    second = scanned(client, mum, "TWO")
    listed = {p["id"]: p["duplicate"] for p in photos(client, mum)}
    assert listed == {first["id"]: False, second["id"]: True}


def test_a_booked_photo_still_counts_for_duplicates(client):
    mum = register(client, "mum")
    bank = create_account(client, mum)
    data = image_png("MIGROS 12.50")
    first = scan(client, mum, data).json()
    attachment = opened(client, mum, first["id"])["attachment_id"]
    booked = client.post(
        f"{BASE_URL}/transactions",
        json={"account_id": bank, "items": items(client), "attachment_ids": [attachment]},
        headers=mum,
    )
    assert booked.status_code == 200, booked.text
    again = scan(client, mum, data).json()
    assert [(p["id"], p["duplicate"]) for p in photos(client, mum)] == [(again["id"], True)]


def test_different_receipts_are_not_duplicates(client):
    mum = register(client, "mum")
    scanned(client, mum, "ONE")
    scanned(client, mum, "TWO")
    assert [p["duplicate"] for p in photos(client, mum)] == [False, False]


def test_photo_deleted_while_read_doesnt_stop_the_others(client, ai, monkeypatch):
    # Removed on the scan screen while the AI reads it: the reader goes on with the next photo
    mum = register(client, "mum")
    ai.down = True
    first, second = scanned(client, mum, "ONE"), scanned(client, mum, "TWO")
    ai.down = False
    with database.SessionLocal() as db:
        db.query(models.InboxPhoto).update({"read_state": "waiting"})
        db.commit()
    real = receipt_ai.ai_draft

    def removed_meanwhile(*args):
        if not removed:
            removed.append(client.delete(f"{PHOTOS}/{first['id']}", headers=mum).status_code)
        return real(*args)

    removed: list = []
    monkeypatch.setattr(receipt_ai, "ai_draft", removed_meanwhile)
    assert scans.read_waiting() == 1
    assert removed == [200]
    assert [(p["id"], p["read_state"]) for p in photos(client, mum)] == [(second["id"], "read")]


def test_photo_uploaded_while_the_reader_finishes_is_read(client, ai, monkeypatch):
    # A photo that arrives just as the running reader lets go: its own run found the reader busy, so the running one
    # looks again after letting go, instead of the photo waiting for the next sweep
    mum = register(client, "mum")
    ai.down = True
    late = scanned(client, mum, "LATE")
    ai.down = False
    lock = scans.reading

    class Busy:
        def acquire(self, blocking=True):
            return lock.acquire(blocking)

        def release(self):
            if not arrived:
                arrived.append(late["id"])
                with database.SessionLocal() as db:
                    db.get(models.InboxPhoto, late["id"]).read_state = "waiting"
                    db.commit()
                # Its own run: the reader is still busy
                assert scans.read_waiting() == 0
            lock.release()

    arrived: list = []
    monkeypatch.setattr(scans, "reading", Busy())
    scanned(client, mum, "FIRST")
    assert arrived == [late["id"]]
    assert states(client, mum) == ["read", "read"]
