"""Whether the bank confirmed a booking, and the account's open points (bank import, part 2). Invented data only."""

from files import image_png
from test_bank_import import HOUSEHOLD, account, bank_file, line
from test_import import upload

from app import database, models
from helpers import BASE_URL, category_id, register

ACCOUNTS = f"{BASE_URL}/accounts"


def setup(client):
    mum = register(client, "mum")
    return mum, account(client, mum, "Household", HOUSEHOLD)


def statement(client, headers, *lines):
    response = upload(client, headers, bank_file(*lines), name="export.csv", path="import")
    assert response.status_code == 200, response.text


def typed(client, headers, account_id, amount=30.0, day="2026-09-03", category="Groceries"):
    body = {"account_id": account_id, "category_id": category_id(client, category), "amount": amount}
    body["date"] = f"{day}T12:00:00Z"
    response = client.post(f"{BASE_URL}/transactions", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def listed(client, headers, account_id, **params):
    response = client.get(f"{ACCOUNTS}/{account_id}/transactions", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return {t["id"]: t for t in response.json()}


def state(client, headers, account_id, transaction_id):
    return listed(client, headers, account_id)[transaction_id]["state"]


def card(client, headers, account_id):
    return next(a for a in client.get(ACCOUNTS, headers=headers).json() if a["id"] == account_id)


def test_no_states_before_first_import(client):
    mum, account_id = setup(client)
    booking = typed(client, mum, account_id)
    assert state(client, mum, account_id, booking) == {
        "confirmation": None,
        "receipt_missing": False,
        "differs": False,
    }
    assert (card(client, mum, account_id)["open_points"], card(client, mum, account_id)["not_confirmed"]) == (0, 0)


def test_confirmed_by_import(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Zahlung Muster", "-5"))
    [booking] = listed(client, mum, account_id).values()
    assert booking["state"]["confirmation"] == "confirmed"
    assert [(r["text"], r["amount"]) for r in booking["bank_rows"]] == [("Zahlung Muster", -5.0)]


def test_not_confirmed_then_no_payment(client):
    mum, account_id = setup(client)
    booking = typed(client, mum, account_id)
    statement(client, mum, line("Zahlung Muster", "-5", booked="2026-09-09"))
    assert state(client, mum, account_id, booking)["confirmation"] == "not_confirmed"
    statement(client, mum, line("Zahlung Beispiel", "-6", booked="2026-09-10"))
    assert state(client, mum, account_id, booking)["confirmation"] == "no_payment"


def test_partly_paid(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Zahlung Muster", "-40"))
    booking = typed(client, mum, account_id, amount=100)
    with database.SessionLocal() as db:
        db.query(models.BankRow).one().transaction_id = booking
        db.commit()
    assert state(client, mum, account_id, booking)["confirmation"] == "partly_paid"


def test_receipt_missing_from_rule(client):
    mum, account_id = setup(client)
    client.post(
        f"{BASE_URL}/import/rules",
        json={"text": "MUSTER", "category_id": category_id(client, "Groceries"), "receipt_expected": True},
        headers=mum,
    )
    statement(client, mum, line("Einkauf TWINT Muster", "-84.30"), line("Zahlung Beispiel", "-5"))
    bookings = {t["description"]: t for t in listed(client, mum, account_id).values()}
    muster, other = bookings["Einkauf TWINT Muster"], bookings["Zahlung Beispiel"]
    assert (muster["receipt_expected"], muster["state"]["receipt_missing"]) == (True, True)
    assert other["state"]["receipt_missing"] is False
    response = client.post(
        f"{BASE_URL}/transactions/{muster['id']}/attachments",
        files={"file": ("beleg.png", image_png())},
        headers=mum,
    )
    assert response.status_code == 200, response.text
    assert state(client, mum, account_id, muster["id"])["receipt_missing"] is False


def test_differs_and_accept(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Zahlung Muster", "-5"))
    [booking] = listed(client, mum, account_id)
    with database.SessionLocal() as db:
        db.get(models.Transaction, booking).difference = -2.5
        db.commit()
    assert state(client, mum, account_id, booking)["differs"] is True
    response = client.put(f"{BASE_URL}/transactions/{booking}", json={"difference_accepted": True}, headers=mum)
    assert response.status_code == 200, response.text
    assert state(client, mum, account_id, booking)["differs"] is False


def test_small_difference_doesnt_warn(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Zahlung Muster", "-5"))
    [booking] = listed(client, mum, account_id)
    with database.SessionLocal() as db:
        db.get(models.Transaction, booking).difference = 0.9
        db.commit()
    assert state(client, mum, account_id, booking)["differs"] is False


def test_cash_has_no_state(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Zahlung Muster", "-5"))
    client.put(f"{ACCOUNTS}/{account_id}", json={"type": "CASH"}, headers=mum)
    booking = typed(client, mum, account_id)
    assert state(client, mum, account_id, booking)["confirmation"] is None
    assert card(client, mum, account_id)["open_points"] == 0


def test_open_filter_and_summary(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Zahlung Muster", "-5", booked="2026-09-20"))
    open_one = typed(client, mum, account_id, amount=30)
    typed(client, mum, account_id, amount=12, day="2026-09-25")
    assert len(listed(client, mum, account_id)) == 3
    assert set(listed(client, mum, account_id, open=1)) == {open_one} | {
        t for t, b in listed(client, mum, account_id).items() if b["state"]["confirmation"] == "not_confirmed"
    }
    assert len(listed(client, mum, account_id, open=1)) == 2
    summary = card(client, mum, account_id)
    assert (summary["open_points"], summary["not_confirmed"]) == (2, -42.0)


def test_toggle_receipt_expected(client):
    mum, account_id = setup(client)
    booking = typed(client, mum, account_id)
    response = client.put(f"{BASE_URL}/transactions/{booking}", json={"receipt_expected": True}, headers=mum)
    assert response.status_code == 200, response.text
    assert response.json()["receipt_expected"] is True
    receipt = client.post(
        f"{BASE_URL}/transactions",
        json={
            "account_id": account_id,
            "items": [{"name": "Brot", "amount": 3.5, "category_id": category_id(client, "Groceries")}],
        },
        headers=mum,
    ).json()
    response = client.put(f"{BASE_URL}/transactions/{receipt['id']}", json={"receipt_expected": True}, headers=mum)
    assert response.status_code == 200, response.text


def test_accounts_list_loads_states_in_few_queries(client):
    from sqlalchemy import event

    mum, account_id = setup(client)
    statement(client, mum, *[line(f"Zahlung {i}", "-5", booked=f"2026-09-{i + 1:02d}") for i in range(25)])
    for i in range(25):
        typed(client, mum, account_id, amount=1 + i)
    queries = []
    listener = lambda *args: queries.append(1)  # noqa: E731
    event.listen(database.engine, "before_cursor_execute", listener)
    try:
        assert client.get(ACCOUNTS, headers=mum).status_code == 200
        assert client.get(f"{ACCOUNTS}/{account_id}/transactions", params={"open": 1}, headers=mum).status_code == 200
    finally:
        event.remove(database.engine, "before_cursor_execute", listener)
    # Not one query per booking (50 bookings here)
    assert len(queries) < 40
