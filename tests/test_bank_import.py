"""The Raiffeisen CSV uploaded directly in the import: lines find their account by IBAN (bank import, part 1).

All IBANs, texts and amounts are invented (the repository is public).
"""

import hashlib

import pytest

from helpers import BASE_URL, balance, category_id, register, user_id
from test_import import upload

HEADER = "IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date"
HOUSEHOLD = "CH93 0076 2011 6238 5295 7"
JOINT = "CH56 0483 5012 3456 7800 9"
CARD = "Einkauf Bäckerei Muster 06.09.2026, 08:45, Debit Mastercard-Nr. 123456xxxxxx1234"


def line(text, amount, booked="2026-09-01", iban="CH9300762011623852957", saldo="1000.0"):
    return f"{iban};{booked} 00:00:00.0;{text};{amount};{saldo};{booked} 00:00:00.0"


def bank_file(*lines):
    return "\n".join([HEADER, *lines]) + "\n"


def account(client, headers, name, iban):
    response = client.post(f"{BASE_URL}/accounts", json={"name": name, "type": "BANK", "iban": iban}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def preview(client, headers, content, **data):
    response = upload(client, headers, content, name="export.csv", **data)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    account(client, headers, "Household", HOUSEHOLD)
    return headers


def test_bank_rows_go_to_account_by_iban(client, mum):
    joint = account(client, mum, "Joint", JOINT)
    result = preview(
        client,
        mum,
        bank_file(
            line("Zahlung Muster Versand", "-2.0"), line("Gutschrift Muster AG", "100", iban=JOINT.replace(" ", ""))
        ),
    )
    out, credit = result["rows"]
    assert (out["status"], out["account"], out["amount"], out["category"]) == ("ok", "Household", "2.00", "Unsorted")
    assert (credit["status"], credit["account"], credit["category"]) == ("ok", "Joint", "Other Income")
    assert (
        upload(client, mum, bank_file(line("Gutschrift Muster AG", "100", iban=JOINT)), path="import").json()[
            "imported"
        ]
        == 1
    )
    assert balance(client, mum, joint) == 100


def test_card_line_uses_purchase_date_and_merchant(client, mum):
    [row] = preview(client, mum, bank_file(line(CARD, "-22.10", booked="2026-09-08")))["rows"]
    assert row["description"] == "Bäckerei Muster"
    assert row["date"] == "2026-09-06T08:45:00+02:00"
    assert upload(client, mum, bank_file(line(CARD, "-22.10")), path="import").status_code == 200
    household = client.get(f"{BASE_URL}/accounts", headers=mum).json()[0]["id"]
    [booked] = client.get(f"{BASE_URL}/accounts/{household}/transactions", headers=mum).json()
    assert booked["date"].startswith("2026-09-06T06:45")


def test_text_loses_iban_and_card_number(client, mum):
    text = "Zahlung an CH56 0483 5012 3456 7800 9 Muster, Debit Mastercard-Nr. 123456xxxxxx1234"
    [row] = preview(client, mum, bank_file(line(text, "-5")))["rows"]
    assert "CH56" not in row["description"] and "1234" not in row["description"]
    assert row["description"] == "Zahlung an Muster"


def test_unknown_iban_is_an_error(client, mum):
    content = bank_file(line("Zahlung Muster", "-5", iban=JOINT.replace(" ", "")))
    [row] = preview(client, mum, content)["rows"]
    assert row["status"] == "error"
    assert row["errors"] == [f"No account has the IBAN {JOINT} (add it to the account in Settings)"]
    assert upload(client, mum, content, path="import").status_code == 400


def test_iban_of_unwritable_account(client, mum):
    dad = register(client, "dad")
    account(client, dad, "Dad bank", JOINT)
    client.put(f"{BASE_URL}/shares/{user_id(client, mum, 'mum')}", json={"level": "VIEW"}, headers=dad)
    [row] = preview(client, mum, bank_file(line("Zahlung Muster", "-5", iban=JOINT)))["rows"]
    assert row["status"] == "error"
    assert "No account has the IBAN" in row["errors"][0]


def test_child_cannot_upload_bank_file(client, mum):
    teen = register(client, "teen", role="CHILD", by=mum)
    response = upload(client, teen, bank_file(line("Zahlung Muster", "-5")))
    assert response.status_code == 403
    assert response.json()["detail"] == "Only parents can import bank statements"


def test_zero_amount_skipped(client, mum):
    result = preview(client, mum, bank_file(line("Zinsabschluss", "0.0"), line("Zahlung Muster", "-5")))
    zero, paid = result["rows"]
    assert (zero["status"], zero["note"]) == ("skipped", "Amount 0, not booked")
    assert (result["ok"], result["skipped"]) == (1, 1)
    assert upload(client, mum, bank_file(line("Zinsabschluss", "0.0")), path="import").json()["imported"] == 0


def test_windows_1252_file(client, mum):
    content = bank_file(line("Übertrag auf Sparkonto", "-50")).encode("cp1252")
    [row] = preview(client, mum, content)["rows"]
    assert (row["status"], row["description"]) == ("ok", "Übertrag auf Sparkonto")
    other = "date,account,category,amount\n2026-09-01,Bäckerei,Unsorted,5\n".encode("cp1252")
    response = upload(client, mum, other)
    assert response.status_code == 400


def test_reference_matches_converter(client, mum):
    # tools/converters/bank.py: "bank:" + sha256 of the raw iban|booked at|text|amount|balance, first 16 hex
    raw = line("Zahlung Muster", "-5.5")
    iban, booked, text, amount, saldo, _ = raw.split(";")
    digest = hashlib.sha256("|".join([iban, booked, text, amount, saldo]).encode("utf-8")).hexdigest()[:16]
    [row] = preview(client, mum, bank_file(raw))["rows"]
    assert row["reference"] == "bank:" + digest


def test_overlap_is_duplicate(client, mum):
    first = [line("Zahlung Muster", "-5"), line("Gutschrift Muster", "20", booked="2026-09-02")]
    assert upload(client, mum, bank_file(*first), path="import").json()["imported"] == 2
    result = preview(client, mum, bank_file(*first, line("Zahlung Beispiel", "-7", booked="2026-09-03")))
    assert (result["ok"], result["duplicates"]) == (1, 2)
    assert upload(client, mum, bank_file(*first), path="import").json()["imported"] == 0


def test_rules_and_fallback(client, mum):
    client.post(
        f"{BASE_URL}/import/rules",
        json={"text": "MUSTER", "category_id": category_id(client, "Groceries")},
        headers=mum,
    )
    rule, fallback, income = preview(
        client,
        mum,
        bank_file(line("Einkauf TWINT Muster Stans", "-5"), line("Zahlung Beispiel", "-7"), line("Zins", "1")),
    )["rows"]
    assert (rule["category"], rule["source"], rule["rule"]) == ("Groceries", "rule", "MUSTER")
    assert (fallback["category"], fallback["source"]) == ("Unsorted", "fallback")
    assert (income["category"], income["source"]) == ("Other Income", "fallback")


def test_change_source(client, mum):
    [row] = preview(client, mum, bank_file(line("Zahlung Beispiel", "-7")), changes='{"2": {"category": "Clothing"}}')[
        "rows"
    ]
    assert (row["category"], row["source"]) == ("Clothing", "change")


def test_transfer_rule(client, mum):
    client.post(
        f"{BASE_URL}/import/rules",
        json={"text": "Übertrag", "category_id": category_id(client, "Transfer")},
        headers=mum,
    )
    [row] = preview(client, mum, bank_file(line("Übertrag auf Sparkonto", "-50")))["rows"]
    assert (row["category"], row["direction"], row["status"]) == ("Transfer", "out", "ok")


def test_balance_check(client, mum):
    household = client.get(f"{BASE_URL}/accounts", headers=mum).json()[0]["id"]
    content = bank_file(
        line("Zahlung Muster", "-5", booked="2026-09-02", saldo="995.0"),
        line("Gutschrift Muster", "20", booked="2026-09-01", saldo="1000.0"),
    )
    [check] = preview(client, mum, content)["balances"]
    assert check == {"account_id": household, "account": "Household", "file_balance": 995.0, "app_balance": 15.0}


def test_normal_csv_unchanged(client, mum):
    content = "date,account,category,amount\n2026-09-01,Household,Groceries,5\n"
    result = preview(client, mum, content)
    assert result["rows"][0]["source"] is None
    assert "balances" not in result
