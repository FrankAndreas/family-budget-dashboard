"""A receipt that comes after the statement goes onto the bank booking that paid it (bank import, part 2)."""

from files import image_png
from test_bank_links import imported, items
from test_reconcile_states import setup

from helpers import BASE_URL, balance, category_id, register, user_id


def payments(client, headers, account_id, day, total):
    return client.get(
        f"{BASE_URL}/accounts/{account_id}/payments", params={"date": day, "total": total}, headers=headers
    )


def test_payments_for_receipt(client):
    mum, account_id = setup(client)
    booking = imported(client, mum, account_id, text="Einkauf TWINT Muster Laden")
    response = payments(client, mum, account_id, "2026-08-30", 84.30)
    assert response.status_code == 200, response.text
    assert [p["id"] for p in response.json()] == [booking["id"]]
    assert payments(client, mum, account_id, "2026-09-05", 84.30).json() == []
    assert payments(client, mum, account_id, "2026-08-01", 84.30).json() == []
    assert payments(client, mum, account_id, "2026-08-30", 90).json() == []
    assert [p["id"] for p in payments(client, mum, account_id, "2026-08-30", 85.0).json()] == [booking["id"]]


def test_booking_with_items_is_no_candidate(client):
    mum, account_id = setup(client)
    booking = imported(client, mum, account_id)
    client.put(f"{BASE_URL}/transactions/{booking['id']}", json={"items": items(client, 84.3)}, headers=mum)
    assert payments(client, mum, account_id, "2026-08-30", 84.30).json() == []


def test_receipt_onto_payment_keeps_balance(client):
    mum, account_id = setup(client)
    booking = imported(client, mum, account_id)
    pending = client.post(f"{BASE_URL}/attachments", files={"file": ("beleg.png", image_png())}, headers=mum).json()
    body = {
        "items": items(client, 50.0, 33.4, category="Clothing"),
        "date": "2026-08-30T12:00:00",
        "description": "Muster Laden",
        "attachment_ids": [pending["id"]],
    }
    response = client.put(f"{BASE_URL}/transactions/{booking['id']}", json=body, headers=mum)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["amount"] == -84.3
    assert result["category_id"] == category_id(client, "Clothing")
    assert result["date"].startswith("2026-08-30")
    assert result["state"] == {"confirmation": "confirmed", "receipt_missing": False, "differs": False}
    assert balance(client, mum, account_id) == -84.3


def test_payments_need_write_access(client):
    mum, account_id = setup(client)
    imported(client, mum, account_id)
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/shares/{user_id(client, mum, 'dad')}", json={"level": "VIEW"}, headers=mum)
    assert payments(client, dad, account_id, "2026-08-30", 84.30).status_code == 403
