"""A receipt fits the bank amount; bank lines are linked, unlinked and booked by hand (bank import, part 2)."""

from test_bank_import import HOUSEHOLD, JOINT, account, bank_file, line
from test_reconcile_states import listed, setup, statement, typed

from helpers import BASE_URL, balance, category_id, register, user_id


def items(client, *amounts, category="Groceries"):
    return [
        {"name": f"Artikel {i}", "amount": a, "category_id": category_id(client, category)}
        for i, a in enumerate(amounts)
    ]


def imported(client, headers, account_id, amount="-84.30", text="Einkauf TWINT Muster"):
    statement(client, headers, line(text, amount))
    return next(t for t in listed(client, headers, account_id).values() if t["description"] == text)


def put_items(client, headers, booking_id, *amounts, **extra):
    body = {"items": items(client, *amounts), **extra}
    response = client.put(f"{BASE_URL}/transactions/{booking_id}", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def rows(client, headers, account_id, **params):
    response = client.get(f"{BASE_URL}/accounts/{account_id}/bank-rows", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_items_fitted_to_bank(client):
    mum, account_id = setup(client)
    booking = imported(client, mum, account_id)
    result = put_items(client, mum, booking["id"], 50.0, 33.4)
    assert result["amount"] == -84.3
    assert [(i["name"], i["amount"]) for i in result["items"]][-1] == ("Difference", 0.9)
    assert result["difference"] == 0.9
    assert result["state"] == {"confirmation": "confirmed", "receipt_missing": False, "differs": False}
    assert balance(client, mum, account_id) == -84.3


def test_items_equal_to_bank_no_difference(client):
    mum, account_id = setup(client)
    booking = imported(client, mum, account_id)
    result = put_items(client, mum, booking["id"], 50.0, 34.3)
    assert len(result["items"]) == 2
    assert result["difference"] is None


def test_negative_difference(client):
    mum, account_id = setup(client)
    booking = imported(client, mum, account_id)
    result = put_items(client, mum, booking["id"], 86.0)
    assert result["items"][-1]["amount"] == -1.7
    assert result["amount"] == -84.3
    assert result["state"]["differs"] is True


def test_german_difference_item(client):
    mum, account_id = setup(client)
    booking = imported(client, mum, account_id)
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=mum)
    response = client.put(f"{BASE_URL}/transactions/{booking['id']}", json={"items": items(client, 80.0)}, headers=mum)
    assert response.json()["items"][-1]["name"] == "Differenz"


def unlinked_row(client, headers, account_id, amount="-30"):
    """A bank line whose booking was deleted."""
    booking = imported(client, headers, account_id, amount=amount, text="Zahlung Beispiel")
    client.delete(f"{BASE_URL}/transactions/{booking['id']}", headers=headers)
    [row] = rows(client, headers, account_id, unlinked=1)
    return row


def test_link_and_unlink(client):
    mum, account_id = setup(client)
    row = unlinked_row(client, mum, account_id)
    booking = typed(client, mum, account_id, amount=30, day="2026-09-01")
    response = client.post(f"{BASE_URL}/transactions/{booking}/bank-rows/{row['id']}", headers=mum)
    assert response.status_code == 200, response.text
    assert response.json()["state"]["confirmation"] == "confirmed"
    assert rows(client, mum, account_id, unlinked=1) == []
    response = client.delete(f"{BASE_URL}/transactions/{booking}/bank-rows/{row['id']}", headers=mum)
    assert response.status_code == 200, response.text
    assert response.json()["state"]["confirmation"] == "not_confirmed"
    assert [r["id"] for r in rows(client, mum, account_id, unlinked=1)] == [row["id"]]


def test_link_moves_row(client):
    mum, account_id = setup(client)
    booking = imported(client, mum, account_id, amount="-30")
    [row] = booking["bank_rows"]
    other = typed(client, mum, account_id, amount=30)
    client.post(f"{BASE_URL}/transactions/{other}/bank-rows/{row['id']}", headers=mum)
    found = listed(client, mum, account_id)
    assert found[booking["id"]]["bank_rows"] == []
    assert [r["id"] for r in found[other]["bank_rows"]] == [row["id"]]


def test_link_other_account_refused(client):
    mum, account_id = setup(client)
    row = unlinked_row(client, mum, account_id)
    joint = account(client, mum, "Joint", JOINT)
    booking = typed(client, mum, joint)
    response = client.post(f"{BASE_URL}/transactions/{booking}/bank-rows/{row['id']}", headers=mum)
    assert response.status_code == 400
    assert response.json()["detail"] == "That bank line belongs to another account"


def test_link_needs_write_access(client):
    mum, account_id = setup(client)
    row = unlinked_row(client, mum, account_id)
    booking = typed(client, mum, account_id)
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/shares/{user_id(client, mum, 'dad')}", json={"level": "VIEW"}, headers=mum)
    assert client.post(f"{BASE_URL}/transactions/{booking}/bank-rows/{row['id']}", headers=dad).status_code == 403
    assert rows(client, dad, account_id)
    assert (
        client.post(f"{BASE_URL}/bank-rows/{row['id']}/book", json={"category_id": "x"}, headers=dad).status_code == 403
    )


def test_list_unlinked_rows(client):
    mum, account_id = setup(client)
    imported(client, mum, account_id)
    row = unlinked_row(client, mum, account_id)
    assert len(rows(client, mum, account_id)) == 2
    assert [r["id"] for r in rows(client, mum, account_id, unlinked=1)] == [row["id"]]


def test_book_unlinked_row(client):
    mum, account_id = setup(client)
    row = unlinked_row(client, mum, account_id)
    url = f"{BASE_URL}/bank-rows/{row['id']}/book"
    response = client.post(url, json={"category_id": category_id(client, "Groceries")}, headers=mum)
    assert response.status_code == 200, response.text
    booked = response.json()
    assert (booked["amount"], booked["date"][:10], booked["description"]) == (-30.0, "2026-09-01", "Zahlung Beispiel")
    assert booked["state"]["confirmation"] == "confirmed"
    again = client.post(url, json={"category_id": category_id(client, "Groceries")}, headers=mum)
    assert again.status_code == 400
    assert again.json()["detail"] == "This bank line already has a booking"


def test_book_category_must_fit(client):
    mum, account_id = setup(client)
    row = unlinked_row(client, mum, account_id)
    url = f"{BASE_URL}/bank-rows/{row['id']}/book"
    assert client.post(url, json={"category_id": category_id(client, "Salary")}, headers=mum).status_code == 400
    assert client.post(url, json={"category_id": category_id(client, "Settle up")}, headers=mum).status_code == 400
    response = client.post(url, json={"category_id": category_id(client, "Transfer")}, headers=mum)
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == -30.0


def test_unlinked_row_is_an_open_point(client):
    mum, account_id = setup(client)
    unlinked_row(client, mum, account_id)
    accounts = client.get(f"{BASE_URL}/accounts", headers=mum).json()
    assert accounts[0]["open_points"] == 1
    assert HOUSEHOLD and bank_file  # used by the helpers above
