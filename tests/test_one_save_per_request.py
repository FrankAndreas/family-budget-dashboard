"""Architecture review 2026-11-07: a booking request saves once, after every check passed; a rejected change leaves
nothing half saved."""

from helpers import BASE_URL, add_transaction, category_id, create_account, register


def booking(client, headers, account, transaction_id):
    listed = client.get(f"{BASE_URL}/accounts/{account}/transactions", headers=headers).json()
    return next(t for t in listed if t["id"] == transaction_id)


def setup(client):
    headers = register(client, "mum")
    account = create_account(client, headers, "Bank")
    created = add_transaction(client, headers, account, category_id(client, "Groceries"), 10, description="Coop")
    return headers, account, created.json()


def test_flag_not_kept_when_the_rest_is_rejected(client):
    headers, account, created = setup(client)
    url = f"{BASE_URL}/transactions/{created['id']}"
    response = client.put(url, json={"receipt_expected": True, "category_id": "missing"}, headers=headers)
    assert response.status_code == 400
    assert booking(client, headers, account, created["id"])["receipt_expected"] is False


def test_text_not_kept_when_the_purchase_is_rejected(client):
    headers, account, created = setup(client)
    url = f"{BASE_URL}/transactions/{created['id']}"
    response = client.put(url, json={"description": "Changed", "asset_purchase": True}, headers=headers)
    assert response.status_code == 400
    assert booking(client, headers, account, created["id"])["description"] == "Coop"


def test_no_booking_when_the_purchase_is_rejected(client):
    headers = register(client, "mum")
    account = create_account(client, headers, "Bank")
    response = add_transaction(client, headers, account, category_id(client, "Groceries"), 10, asset_purchase=True)
    assert response.status_code == 400
    assert client.get(f"{BASE_URL}/accounts/{account}/transactions", headers=headers).json() == []


def test_flag_alone_is_saved(client):
    headers, account, created = setup(client)
    url = f"{BASE_URL}/transactions/{created['id']}"
    assert client.put(url, json={"receipt_expected": True}, headers=headers).status_code == 200
    assert booking(client, headers, account, created["id"])["receipt_expected"] is True
