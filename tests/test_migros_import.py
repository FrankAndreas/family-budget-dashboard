"""Migros receipts from the Cumulus export: onto their bank payment, articles by rule → AI → fallback, learnt as rules.
Invented stores and articles only."""

import json

import pytest
from test_article_ai import Fake
from test_bank_import import line
from test_bank_matching import receipt as typed_receipt
from test_reconcile_states import listed, setup, statement

from app import receipt_ai
from helpers import BASE_URL, category_id, create_account, register

HEADER = "Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz"
# Brot 3.50 + Zahnpasta 6.95 + Karotten 1.95 = 12.40
FIRST = [
    "12.09.2026;11:35:25;Filiale Muster;270;133;Brot;1;0.00;3.50",
    "12.09.2026;11:35:25;Filiale Muster;270;133;Zahnpasta;1;0.00;6.95",
    "12.09.2026;11:35:25;Filiale Muster;270;133;Karotten;1;0.00;1.95",
]
FIRST_KEY = "migros:12.09.2026:11:35:25:Filiale Muster:270:133"


def migros(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


def send(client, headers, content, path="import/migros/preview", choices=None, ai=False):
    data = {"choices": json.dumps(choices)} if choices else {}
    if ai:
        data["ai"] = "1"
    return client.post(
        f"{BASE_URL}/{path}", files={"file": ("kassenbeleg.csv", content.encode())}, data=data, headers=headers
    )


def preview(client, headers, content, **kwargs):
    response = send(client, headers, content, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def run(client, headers, content, choices):
    return send(client, headers, content, path="import/migros", choices=choices)


def choices_of(result, **receipts):
    """What the frontend sends back: the preview's articles and receipts as shown, with some receipts changed."""
    return {
        "articles": result["articles"],
        "receipts": {
            r["key"]: {"include": r["include"], "payment": r["payment"], "account_id": r["account_id"]}
            | receipts.get(r["key"], {})
            for r in result["receipts"]
        },
    }


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setenv("INFOMANIAK_AI_TOKEN", "t")
    monkeypatch.setenv("INFOMANIAK_AI_PRODUCT_ID", "p")
    monkeypatch.delenv("RECEIPT_AI_READS_PER_HOUR", raising=False)
    fake = Fake(json.dumps({"Zahnpasta": {"category": "Healthcare", "tags": []}}))
    monkeypatch.setattr(receipt_ai, "client_for", lambda settings: fake)
    return fake


def rules(client, headers):
    return {
        r["name"]: (r["category"], r["tag_ids"])
        for r in client.get(f"{BASE_URL}/article-rules", headers=headers).json()
    }


def test_preview_finds_the_payment_and_books_onto_it(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Einkauf TWINT Migros", "-12.40", booked="2026-09-13"))
    [payment] = listed(client, mum, account_id)
    result = preview(client, mum, migros(*FIRST))
    [found] = result["receipts"]
    assert (found["key"], found["total"], found["status"], found["include"]) == (FIRST_KEY, 12.4, "new", True)
    assert (found["date"], found["time"], found["store"]) == ("2026-09-12", "11:35:25", "Filiale Muster")
    assert found["payment"] == payment and [p["id"] for p in found["payments"]] == [payment]

    response = run(client, mum, migros(*FIRST), choices_of(result))
    assert response.status_code == 200, response.text
    assert response.json()["onto_payments"] == 1 and response.json()["booked"] == 0
    [booking] = listed(client, mum, account_id).values()
    assert booking["id"] == payment
    assert (booking["description"], booking["reference"], booking["amount"]) == (
        "Migros Filiale Muster",
        FIRST_KEY,
        -12.4,
    )
    assert [i["name"] for i in booking["items"]] == ["Brot", "Zahnpasta", "Karotten"]
    assert booking["state"]["confirmation"] == "confirmed"


def test_no_payment_books_new_and_bank_import_finds_it_later(client):
    mum, account_id = setup(client)
    result = preview(client, mum, migros(*FIRST))
    [found] = result["receipts"]
    assert (found["payment"], found["account_id"]) == ("new", account_id)
    assert run(client, mum, migros(*FIRST), choices_of(result)).json()["booked"] == 1
    [booking] = listed(client, mum, account_id).values()
    statement(client, mum, line("Einkauf TWINT Migros", "-12.40", booked="2026-09-13"))
    found = listed(client, mum, account_id)
    assert list(found) == [booking["id"]]
    assert found[booking["id"]]["state"]["confirmation"] == "confirmed"


def test_rule_then_ai_then_fallback(client, ai):
    mum, account_id = setup(client)
    client.post(
        f"{BASE_URL}/article-rules",
        json={"name": "Brot", "category_id": category_id(client, "Other Expense")},
        headers=mum,
    )
    content = migros(*FIRST, "12.09.2026;11:35:25;Filiale Muster;270;133;brot ;1;0.00;1.00")
    result = preview(client, mum, content, ai=True)
    sources = {name: (a["source"], a["category_id"]) for name, a in result["articles"].items()}
    assert sources == {
        "brot": ("rule", category_id(client, "Other Expense")),
        "zahnpasta": ("ai", category_id(client, "Healthcare")),
        "karotten": ("fallback", category_id(client, "Groceries")),
    }
    # One question, with each unknown article once
    [question] = ai.questions
    assert json.loads(question.split(receipt_ai.ARTICLE_MARKER, 1)[1]) == ["Zahnpasta", "Karotten"]
    assert result["ai"]["status"] == "ok" and result["new_rules"] == 1
    # The receipt's Brot lines are one line (3.50 + 1.00)
    assert [(i["name"], i["amount"]) for i in result["receipts"][0]["lines"]][0] == ("Brot", 4.5)

    assert run(client, mum, content, choices_of(result)).json()["rules"] == 1
    assert rules(client, mum) == {"Brot": ("Other Expense", []), "Zahnpasta": ("Healthcare", [])}


def test_ai_off_leaves_the_fallback_without_rules(client):
    mum, _ = setup(client)
    result = preview(client, mum, migros(*FIRST), ai=True)
    assert {a["source"] for a in result["articles"].values()} == {"fallback"}
    assert result["ai"]["status"] == "off" and result["new_rules"] == 0
    assert run(client, mum, migros(*FIRST), choices_of(result)).json()["rules"] == 0
    assert rules(client, mum) == {}


def test_changed_article_updates_its_rule(client):
    mum, _ = setup(client)
    kinder = client.post(f"{BASE_URL}/tags", json={"name": "Kinder"}, headers=mum).json()["id"]
    client.post(
        f"{BASE_URL}/article-rules", json={"name": "Brot", "category_id": category_id(client, "Groceries")}, headers=mum
    )
    result = preview(client, mum, migros(*FIRST))
    choices = choices_of(result)
    choices["articles"]["brot"] = {
        "category_id": category_id(client, "Other Expense"),
        "tag_ids": [kinder],
        "source": "change",
    }
    again = preview(client, mum, migros(*FIRST), choices=choices)
    assert again["articles"]["brot"]["source"] == "change" and again["new_rules"] == 1
    assert run(client, mum, migros(*FIRST), choices).json()["rules"] == 1
    assert rules(client, mum) == {"Brot": ("Other Expense", [kinder])}


def test_reimport_is_already_imported(client):
    mum, _ = setup(client)
    result = preview(client, mum, migros(*FIRST))
    run(client, mum, migros(*FIRST), choices_of(result))
    [found] = preview(client, mum, migros(*FIRST))["receipts"]
    assert (found["status"], found["include"]) == ("imported", False)
    # Ticked anyway: still not booked again
    again = run(client, mum, migros(*FIRST), choices_of(result))
    assert again.json()["booked"] == 0


def test_maybe_booked_is_unticked(client):
    mum, account_id = setup(client)
    body = {
        "account_id": account_id,
        "date": "2026-09-12T10:00:00Z",
        "description": "Migros",
        "items": [{"name": "Einkauf", "amount": 12.4, "category_id": category_id(client, "Groceries")}],
    }
    assert client.post(f"{BASE_URL}/transactions", json=body, headers=mum).status_code == 200
    [found] = preview(client, mum, migros(*FIRST))["receipts"]
    assert (found["status"], found["include"]) == ("maybe_booked", False)


def test_receipt_not_positive_is_an_error(client):
    mum, account_id = setup(client)
    voucher = "05.09.2026;10:42:10;Beispiel Markt;267;14;CUMULUS BON 5.-;0;0;-5.00"
    result = preview(client, mum, migros(*FIRST, voucher))
    states = {r["store"]: (r["status"], r["include"]) for r in result["receipts"]}
    assert states == {"Filiale Muster": ("new", True), "Beispiel Markt": ("error", False)}
    choices = choices_of(result)
    for found in choices["receipts"].values():
        found["include"] = True
    response = run(client, mum, migros(*FIRST, voucher), choices)
    assert response.status_code == 200, response.text
    assert response.json()["booked"] == 1


def test_voucher_is_a_discount_line_in_the_main_category(client):
    mum, _ = setup(client)
    voucher = "12.09.2026;11:35:25;Filiale Muster;270;133;CUMULUS BON 5.-;0;0;-5.00"
    result = preview(client, mum, migros(*FIRST, voucher))
    [found] = result["receipts"]
    assert found["total"] == 7.4
    assert found["lines"][-1] == {
        "key": "cumulus bon 5.-",
        "name": "CUMULUS BON 5.-",
        "amount": -5.0,
        "category_id": category_id(client, "Groceries"),
        "tag_ids": [],
        "source": "discount",
    }
    assert "cumulus bon 5.-" not in result["articles"]


def test_two_receipts_never_share_a_payment(client):
    mum, account_id = setup(client)
    statement(
        client,
        mum,
        line("Einkauf TWINT Migros", "-12.40", booked="2026-09-13"),
        line("Einkauf Debit Migros", "-12.40", booked="2026-09-14", saldo="987.6"),
    )
    second = [row.replace("11:35:25", "17:02:00").replace(";133;", ";140;") for row in FIRST]
    result = preview(client, mum, migros(*FIRST, *second))
    payments = [r["payment"] for r in result["receipts"]]
    assert len(set(payments)) == 2 and "new" not in payments
    # Chosen twice on purpose: refused
    choices = choices_of(result)
    first, other = choices["receipts"]
    choices["receipts"][other]["payment"] = choices["receipts"][first]["payment"]
    assert send(client, mum, migros(*FIRST, *second), choices=choices).status_code == 400


def test_failed_import_saves_nothing(client, ai):
    mum, account_id = setup(client)
    result = preview(client, mum, migros(*FIRST), ai=True)
    choices = choices_of(result, **{FIRST_KEY: {"account_id": "nope"}})
    assert run(client, mum, migros(*FIRST), choices).status_code in (403, 404)
    assert listed(client, mum, account_id) == {}
    assert rules(client, mum) == {}


def test_other_parents_unshared_account_is_not_offered(client):
    mum, account_id = setup(client)
    dad = register(client, "dad")
    dads = create_account(client, dad, "Dad bank")
    result = preview(client, mum, migros(*FIRST))
    assert [a["id"] for a in result["accounts"]] == [account_id]
    choices = choices_of(result, **{FIRST_KEY: {"account_id": dads}})
    assert run(client, mum, migros(*FIRST), choices).status_code == 403


def test_parents_only_and_migros_files_only(client):
    mum, _ = setup(client)
    kid = register(client, "kid", role="CHILD", by=mum)
    assert send(client, kid, migros(*FIRST)).status_code == 403
    assert send(client, mum, "date,amount\n2026-09-01,3\n").status_code == 400


def test_typed_receipt_on_another_day_is_not_maybe_booked(client):
    mum, account_id = setup(client)
    typed_receipt(client, mum, account_id, "2026-09-20", 12.4)
    [found] = preview(client, mum, migros(*FIRST))["receipts"]
    assert found["status"] == "new"


# The whole-branch review's findings (2026-10-28)


def second_receipt(time="17:02:00", number="140", amounts=None):
    rows = [row.replace("11:35:25", time).replace(";133;", f";{number};") for row in FIRST]
    return rows if amounts is None else [rows[0].replace(";3.50", f";{amounts}")]


def test_exact_match_wins_over_a_near_one(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Einkauf TWINT Migros", "-12.40", booked="2026-09-13"))
    [payment] = listed(client, mum, account_id)
    # A newer receipt of 12.90 (paid by card) is within CHF 1.00, but the older one is exact
    newer = [r.replace("12.09.2026", "14.09.2026") for r in second_receipt(amounts="12.90")]
    result = preview(client, mum, migros(*FIRST, *newer))
    by_store = {r["total"]: r["payment"] for r in result["receipts"]}
    assert by_store == {12.4: payment, 12.9: "new"}


def test_unticked_receipt_leaves_its_payment(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Einkauf TWINT Migros", "-12.40", booked="2026-09-13"))
    [payment] = listed(client, mum, account_id)
    newer_key = "migros:12.09.2026:17:02:00:Filiale Muster:270:140"
    content = migros(*FIRST, *second_receipt())
    result = preview(client, mum, content, choices={"articles": {}, "receipts": {newer_key: {"include": False}}})
    by_key = {r["key"]: (r["include"], r["payment"]) for r in result["receipts"]}
    assert by_key == {newer_key: (False, "new"), FIRST_KEY: (True, payment)}


def test_payment_chosen_for_another_receipt_moves(client):
    mum, account_id = setup(client)
    statement(
        client,
        mum,
        line("Einkauf TWINT Migros", "-12.40", booked="2026-09-13"),
        line("Einkauf Debit Migros", "-12.40", booked="2026-09-14", saldo="987.6"),
    )
    content = migros(*FIRST, *second_receipt())
    first = {r["key"]: r["payment"] for r in preview(client, mum, content)["receipts"]}
    newer_key = "migros:12.09.2026:17:02:00:Filiale Muster:270:140"
    # The person gives the newer receipt the payment the older one had: only that choice is sent
    wanted = first[FIRST_KEY]
    result = preview(client, mum, content, choices={"articles": {}, "receipts": {newer_key: {"payment": wanted}}})
    after = {r["key"]: r["payment"] for r in result["receipts"]}
    assert after[newer_key] == wanted and after[FIRST_KEY] == first[newer_key]
    # Every payment is offered, also the one another receipt holds
    assert all(len(r["payments"]) == 2 for r in result["receipts"])


def test_new_receipts_default_to_the_newest_matched_account(client):
    mum, household = setup(client)
    joint = client.post(
        f"{BASE_URL}/accounts",
        json={"name": "Joint", "type": "BANK", "iban": "CH56 0483 5012 3456 7800 9"},
        headers=mum,
    ).json()["id"]
    statement(client, mum, line("Einkauf TWINT Migros", "-12.40", booked="2026-09-13", iban="CH5604835012345678009"))
    # The newest receipt has no statement line yet: it goes where the matched one went
    newer = [r.replace("12.09.2026", "20.09.2026") for r in second_receipt(amounts="20.00")]
    result = preview(client, mum, migros(*FIRST, *newer))
    by_total = {r["total"]: (r["payment"] != "new", r["account_id"]) for r in result["receipts"]}
    assert by_total[12.4][0] is True
    assert by_total[20.0] == (False, joint)
    assert household != joint


def test_converter_booking_is_already_imported(client):
    mum, account_id = setup(client)
    reference = "migros:2026-09-12:Filiale Muster:270:133:Groceries:"
    add = {
        "account_id": account_id,
        "category_id": category_id(client, "Groceries"),
        "amount": 12.4,
        "date": "2026-09-12T10:00:00Z",
        "description": "Migros Filiale Muster",
        "reference": reference,
    }
    assert client.post(f"{BASE_URL}/transactions", json=add, headers=mum).status_code == 200
    [found] = preview(client, mum, migros(*FIRST))["receipts"]
    assert (found["status"], found["include"]) == ("imported", False)


def test_receipt_expected_is_met_by_the_import(client):
    mum, account_id = setup(client)
    statement(client, mum, line("Einkauf TWINT Migros", "-12.40", booked="2026-09-13"))
    [payment] = listed(client, mum, account_id)
    client.put(f"{BASE_URL}/transactions/{payment}", json={"receipt_expected": True}, headers=mum)
    assert listed(client, mum, account_id)[payment]["state"]["receipt_missing"] is True
    result = preview(client, mum, migros(*FIRST))
    run(client, mum, migros(*FIRST), choices_of(result))
    assert listed(client, mum, account_id)[payment]["state"]["receipt_missing"] is False


def test_line_key_is_the_servers(client):
    mum, _ = setup(client)
    content = migros("12.09.2026;11:35:25;Filiale Muster;270;133;Weißwurst;1;0.00;4.20")
    [found] = preview(client, mum, content)["receipts"]
    assert found["lines"][0]["key"] == "weisswurst"
    choices = {
        "articles": {
            "weisswurst": {"category_id": category_id(client, "Other Expense"), "tag_ids": [], "source": "change"}
        },
        "receipts": {},
    }
    [again] = preview(client, mum, content, choices=choices)["receipts"]
    assert again["lines"][0]["category_id"] == category_id(client, "Other Expense")


def test_failed_import_rolls_back_receipts_already_booked(client):
    mum, account_id = setup(client)
    content = migros(*FIRST, *second_receipt())
    # The newer receipt (booked first) is fine, the older one's account is not
    response = run(client, mum, content, {"articles": {}, "receipts": {FIRST_KEY: {"account_id": "nope"}}})
    assert response.status_code == 404
    assert listed(client, mum, account_id) == {}
