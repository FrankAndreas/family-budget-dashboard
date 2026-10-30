"""Bookings with items (issue #56): the booking's amount is the items' sum, its category the largest item's."""

from helpers import add_member, BASE_URL, admin_headers, category_id, create_account, create_split, register, user_id

TX = f"{BASE_URL}/transactions"


def tag(client, headers, name):
    return client.post(f"{BASE_URL}/tags", json={"name": name}, headers=headers).json()["id"]


def receipt(client, headers, account, items, **extra):
    return client.post(TX, json={"account_id": account, "items": items, **extra}, headers=headers)


def item(name, amount, category, **extra):
    return {"name": name, "amount": amount, "category_id": category, **extra}


def test_receipt_with_items(client):
    mum = register(client, "mum")
    velo = tag(client, admin_headers(client), "Velo")
    account = create_account(client, mum)
    response = receipt(
        client,
        mum,
        account,
        [
            item("Brot", 3.50, category_id(client, "Groceries")),
            item("Velo-Hose", 79.90, category_id(client, "Clothing"), tag_ids=[velo]),
        ],
        description="Migros",
    )
    assert response.status_code == 200, response.text
    booking = response.json()
    assert booking["amount"] == -83.40
    assert booking["category_id"] == category_id(client, "Clothing")
    assert [(i["position"], i["name"], i["amount"], i["tag_ids"]) for i in booking["items"]] == [
        (0, "Brot", 3.50, []),
        (1, "Velo-Hose", 79.90, [velo]),
    ]


def test_main_category_is_the_largest_sum(client):
    mum = register(client, "mum")
    groceries, clothing = category_id(client, "Groceries"), category_id(client, "Clothing")
    booking = receipt(
        client,
        mum,
        create_account(client, mum),
        [item("Brot", 30, groceries), item("Socken", 40, clothing), item("Milch", 20, groceries)],
    ).json()
    assert booking["category_id"] == groceries


def test_discount_line_lowers_the_amount(client):
    mum = register(client, "mum")
    groceries = category_id(client, "Groceries")
    booking = receipt(
        client, mum, create_account(client, mum), [item("Kaffee", 12.00, groceries), item("Aktion", -2.00, groceries)]
    ).json()
    assert booking["amount"] == -10.00


def test_sum_must_be_positive(client):
    mum = register(client, "mum")
    groceries = category_id(client, "Groceries")
    response = receipt(client, mum, create_account(client, mum), [item("Rabatt", -2, groceries)])
    assert response.status_code == 400 and response.json()["detail"] == "The items must add up to more than 0"


def test_items_need_expense_categories(client):
    mum = register(client, "mum")
    response = receipt(client, mum, create_account(client, mum), [item("Lohn", 10, category_id(client, "Salary"))])
    assert response.status_code == 400 and response.json()["detail"] == "Items need an expense category"


def test_unknown_tag_or_person(client):
    mum = register(client, "mum")
    account, groceries = create_account(client, mum), category_id(client, "Groceries")
    assert receipt(client, mum, account, [item("Brot", 3, groceries, tag_ids=["nope"])]).status_code == 400
    assert receipt(client, mum, account, [item("Brot", 3, groceries, person_id="nope")]).status_code == 400


def test_person_must_be_visible(client):
    admin = admin_headers(client)
    kid = register(client, "kid", role="CHILD")
    client.patch(f"{BASE_URL}/me/privacy", json={"privacy_enabled": True}, headers=kid)
    kid_id = user_id(client, kid, "kid")
    response = receipt(
        client,
        admin,
        create_account(client, admin),
        [item("Brot", 3, category_id(client, "Groceries"), person_id=kid_id)],
    )
    assert response.status_code == 400


def test_person_for_an_item(client):
    admin = admin_headers(client)
    add_member(client, "kid")
    kid = user_id(client, admin, "kid")
    booking = receipt(
        client,
        admin,
        create_account(client, admin),
        [item("Schuhe", 50, category_id(client, "Clothing"), person_id=kid)],
    ).json()
    assert booking["items"][0]["person_id"] == kid and booking["member_id"] is None


def test_put_replaces_items(client):
    mum = register(client, "mum")
    groceries = category_id(client, "Groceries")
    booking = receipt(client, mum, create_account(client, mum), [item("Brot", 3, groceries)]).json()
    response = client.put(
        f"{TX}/{booking['id']}", json={"items": [item("Milch", 2, groceries), item("Käse", 8, groceries)]}, headers=mum
    )
    assert response.status_code == 200
    assert [i["name"] for i in response.json()["items"]] == ["Milch", "Käse"] and response.json()["amount"] == -10


def test_put_empty_items_makes_a_plain_booking(client):
    mum = register(client, "mum")
    groceries = category_id(client, "Groceries")
    booking = receipt(client, mum, create_account(client, mum), [item("Brot", 3, groceries)]).json()
    response = client.put(
        f"{TX}/{booking['id']}", json={"items": [], "amount": 7, "category_id": groceries}, headers=mum
    )
    assert response.json()["items"] == [] and response.json()["amount"] == -7


def test_old_edit_on_itemized_booking_is_refused(client):
    mum = register(client, "mum")
    groceries = category_id(client, "Groceries")
    booking = receipt(client, mum, create_account(client, mum), [item("Brot", 3, groceries)]).json()
    response = client.put(f"{TX}/{booking['id']}", json={"amount": 5}, headers=mum)
    assert response.status_code == 400 and response.json()["detail"] == "Change the items instead"
    response = client.put(f"{TX}/{booking['id']}", json={"description": "Migros"}, headers=mum)
    assert response.status_code == 200 and response.json()["amount"] == -3


def test_shared_receipt_follows_items(client):
    admin = admin_headers(client)
    mum = register(client, "mum")
    ids = {u["username"]: u["id"] for u in client.get(f"{BASE_URL}/users", headers=admin).json()}
    split = create_split(client, admin, "Halb", {ids["Admin"]: 50, ids["mum"]: 50}).json()
    groceries = category_id(client, "Groceries")
    booking = receipt(
        client, admin, create_account(client, admin), [item("Brot", 10, groceries)], split_id=split["id"]
    ).json()
    client.put(f"{TX}/{booking['id']}", json={"items": [item("Brot", 30, groceries)]}, headers=admin)
    balance = {b["user_id"]: b["amount"] for b in client.get(f"{BASE_URL}/common/balance", headers=admin).json()}
    assert balance[ids["Admin"]] == 15 and balance[ids["mum"]] == -15
    del mum


def test_category_used_by_items_cannot_be_deleted(client):
    admin = admin_headers(client)
    snacks = client.post(f"{BASE_URL}/categories", json={"name": "Snacks", "type": "EXPENSE"}, headers=admin).json()[
        "id"
    ]
    groceries = category_id(client, "Groceries")
    receipt(client, admin, create_account(client, admin), [item("Brot", 5, groceries), item("Chips", 3, snacks)])
    response = client.delete(f"{BASE_URL}/categories/{snacks}", headers=admin)
    assert response.status_code == 409 and response.json()["detail"] == "Used by 1 receipt item"


def test_items_listed_with_transactions(client):
    mum = register(client, "mum")
    account = create_account(client, mum)
    receipt(client, mum, account, [item("Brot", 3, category_id(client, "Groceries"))])
    listed = client.get(f"{BASE_URL}/accounts/{account}/transactions", headers=mum).json()
    assert [i["name"] for i in listed[0]["items"]] == ["Brot"]


def test_plain_booking_still_needs_amount_and_category(client):
    mum = register(client, "mum")
    assert client.post(TX, json={"account_id": create_account(client, mum)}, headers=mum).status_code == 422


def test_an_item_may_be_zero_or_negative(client):
    """A free item (0) or a discount (negative) is a line of its own; only the receipt total must be above 0."""
    mum = register(client, "mum")
    groceries = category_id(client, "Groceries")
    response = receipt(
        client,
        mum,
        create_account(client, mum),
        [item("Brot", 3.50, groceries), item("Gratis-Tasche", 0, groceries), item("Aktion", -1.00, groceries)],
    )
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == -2.50
    assert [i["amount"] for i in response.json()["items"]] == [3.50, 0, -1.00]
