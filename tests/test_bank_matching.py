"""A bank line confirms the booking it paid instead of booking it again (bank import, part 2). Invented data only."""

import json

from test_bank_import import bank_file, line
from test_bank_links import items
from test_import import upload
from test_reconcile_states import listed, setup, statement, typed

from helpers import BASE_URL, balance, register, user_id


def receipt(client, headers, account_id, day="2026-09-03", *amounts):
    body = {
        "account_id": account_id,
        "date": f"{day}T12:00:00Z",
        "description": "Muster Laden",
        "items": items(client, *(amounts or (50.0, 34.3))),
    }
    response = client.post(f"{BASE_URL}/transactions", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def preview(client, headers, content, matches=None):
    data = {"matches": json.dumps(matches)} if matches else {}
    response = upload(client, headers, content, name="export.csv", **data)
    assert response.status_code == 200, response.text
    return response.json()


def run(client, headers, content, matches=None):
    data = {"matches": json.dumps(matches)} if matches else {}
    return upload(client, headers, content, name="export.csv", path="import", **data)


def test_line_confirms_receipt(client):
    mum, account_id = setup(client)
    booking = receipt(client, mum, account_id)
    content = bank_file(line("Einkauf TWINT Muster Laden", "-84.30", booked="2026-09-05"))
    [row] = preview(client, mum, content)["rows"]
    assert row["match"] == booking
    assert [(m["id"], m["description"], m["amount"]) for m in row["matches"]] == [(booking, "Muster Laden", -84.3)]
    assert run(client, mum, content).json()["imported"] == 1
    found = listed(client, mum, account_id)
    assert list(found) == [booking]
    assert found[booking]["state"]["confirmation"] == "confirmed"
    assert balance(client, mum, account_id) == -84.3


def test_tolerance(client):
    mum, account_id = setup(client)
    booking = receipt(client, mum, account_id)
    content = bank_file(line("Einkauf TWINT Muster Laden", "-85.00", booked="2026-09-05"))
    assert preview(client, mum, content)["rows"][0]["match"] == booking
    run(client, mum, content)
    found = listed(client, mum, account_id)[booking]
    assert (found["amount"], found["items"][-1]["amount"], found["difference"]) == (-85.0, 0.7, 0.7)


def test_too_far_off_doesnt_match(client):
    mum, account_id = setup(client)
    receipt(client, mum, account_id)
    [row] = preview(client, mum, bank_file(line("Einkauf TWINT Muster", "-85.31", booked="2026-09-05")))["rows"]
    assert (row["match"], row["matches"]) == (None, [])


def test_no_match_outside_window_or_sign(client):
    mum, account_id = setup(client)
    receipt(client, mum, account_id, "2026-08-01")
    typed(client, mum, account_id, amount=20, day="2026-09-04", category="Salary")
    late = line("Einkauf TWINT Muster", "-84.30", booked="2026-09-05")
    refund = line("Gutschrift Muster", "-20", booked="2026-09-05")
    early = line("Einkauf TWINT Muster", "-84.30", booked="2026-07-28")
    rows = preview(client, mum, bank_file(late, refund, early))["rows"]
    assert [r["match"] for r in rows] == [None, None, None]


def test_window_edges(client):
    mum, account_id = setup(client)
    booking = receipt(client, mum, account_id, "2026-09-03")
    # The booking may be up to 30 days before the line, or up to 3 days after it
    assert preview(client, mum, bank_file(line("x", "-84.30", booked="2026-10-03")))["rows"][0]["match"] == booking
    assert preview(client, mum, bank_file(line("x", "-84.30", booked="2026-10-04")))["rows"][0]["match"] is None
    assert preview(client, mum, bank_file(line("x", "-84.30", booked="2026-08-31")))["rows"][0]["match"] == booking
    assert preview(client, mum, bank_file(line("x", "-84.30", booked="2026-08-30")))["rows"][0]["match"] is None


def test_candidate_used_once(client):
    mum, account_id = setup(client)
    booking = receipt(client, mum, account_id)
    content = bank_file(
        line("Muster A", "-84.30", booked="2026-09-04"), line("Muster B", "-84.30", booked="2026-09-05")
    )
    first, second = preview(client, mum, content)["rows"]
    assert (first["match"], second["match"]) == (booking, None)
    assert run(client, mum, content).json()["imported"] == 2
    assert len(listed(client, mum, account_id)) == 2


def test_choose_new_or_other(client):
    mum, account_id = setup(client)
    near = receipt(client, mum, account_id, "2026-09-04")
    far = receipt(client, mum, account_id, "2026-09-01")
    content = bank_file(line("Muster", "-84.30", booked="2026-09-05"))
    [row] = preview(client, mum, content)["rows"]
    assert (row["match"], [m["id"] for m in row["matches"]]) == (near, [near, far])
    assert preview(client, mum, content, {"2": far})["rows"][0]["match"] == far
    assert preview(client, mum, content, {"2": "new"})["rows"][0]["match"] is None
    run(client, mum, content, {"2": "new"})
    assert len(listed(client, mum, account_id)) == 3


def test_exact_amount_before_nearer_date(client):
    mum, account_id = setup(client)
    exact = receipt(client, mum, account_id, "2026-09-01")
    receipt(client, mum, account_id, "2026-09-05", 84.0)
    assert preview(client, mum, bank_file(line("Muster", "-84.30", booked="2026-09-05")))["rows"][0]["match"] == exact


def test_unknown_match_refused(client):
    mum, account_id = setup(client)
    content = bank_file(line("Muster", "-84.30", booked="2026-09-05"))
    [row] = preview(client, mum, content, {"2": "nope"})["rows"]
    assert row["status"] == "error"
    assert row["errors"] == ["That booking can't be confirmed by this line"]
    assert run(client, mum, content, {"2": "nope"}).status_code == 400


def test_settle_up_booking_matched(client):
    mum, account_id = setup(client)
    dad = register(client, "dad")
    dad_account = client.post(f"{BASE_URL}/accounts", json={"name": "Dad bank", "type": "BANK"}, headers=dad).json()
    response = client.post(
        f"{BASE_URL}/settlements",
        json={
            "from_user_id": user_id(client, mum, "mum"),
            "to_user_id": user_id(client, mum, "dad"),
            "amount": 150,
            "from_account_id": account_id,
            "to_account_id": dad_account["id"],
            "date": "2026-09-04T12:00:00Z",
        },
        headers=mum,
    )
    assert response.status_code == 200, response.text
    [row] = preview(client, mum, bank_file(line("Dauerauftrag Ausgleich", "-150", booked="2026-09-05")))["rows"]
    assert row["match"] is not None


def test_balance_check_confirmed_only(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Zahlung Muster", "-5", booked="2026-09-01"))
    typed(client, mum, account_id, amount=30, day="2026-09-20")
    booking = receipt(client, mum, account_id)
    content = bank_file(line("Muster", "-84.30", booked="2026-09-05", saldo="910.70"))
    [check] = preview(client, mum, content)["balances"]
    # Confirmed −5, plus the matched −84.30; the unconfirmed −30 doesn't count
    assert check["app_balance"] == -89.3
    assert booking


def test_included_duplicate_keeps_first_bank_row(client):
    from app import database, models

    mum, account_id = setup(client)
    content = bank_file(line("Zahlung Muster", "-5"))
    run(client, mum, content)
    response = upload(client, mum, content, name="export.csv", path="import", include_duplicates="2")
    assert response.status_code == 200, response.text
    assert len(listed(client, mum, account_id)) == 2
    with database.SessionLocal() as db:
        assert db.query(models.BankRow).count() == 1
