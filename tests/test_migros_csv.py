"""The Migros receipt export ("Kassenbeleg") read into receipts. Invented stores and articles only."""

from datetime import datetime

import pytest
from fastapi import HTTPException

from app import migros_csv

HEADER = "Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz"


def file(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


def test_is_migros():
    assert migros_csv.is_migros("﻿" + HEADER + "\r\n12.09.2026;...")
    assert not migros_csv.is_migros("IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date\n")


def test_receipts_grouped_and_cleaned():
    text = file(
        "12.09.2026;11:35:25;Filiale Muster;270;133;Karotten;2;0.00;3.90",
        "12.09.2026;11:35:25;Filiale Muster;270;133;Karotten;-2;0.00;-3.90",
        "12.09.2026;11:35:25;Filiale Muster;270;133;Karotten;1;0.00;1.95",
        "12.09.2026;11:35:25;Filiale Muster;270;133;Brot;1;0.00;3.50",
        "12.09.2026;11:35:25;Filiale Muster;270;133;brot ;1;0.00;3.50",
        "12.09.2026;11:35:25;Filiale Muster;270;133;Milch;0.424;0.10;1.95",
        "12.09.2026;11:35:25;Filiale Muster;270;133;Bonus-Coupon 2x;1;0;0",
        "12.09.2026;11:35:25;Filiale Muster;270;133;CUM10x Pkt Brot;1;0;0",
        "12.09.2026;11:35:25;Filiale Muster;270;133;CUMULUS BON 5.-;0;0;-5.00",
        "05.09.2026;10:42:10;Beispiel Markt;267;14;Zahnpasta;1;0.00;6.95",
        "12.09.2026;09:01:00;Filiale Muster;002;84;Seife;1;0.00;2.40",
    )
    found = migros_csv.receipts(text)
    assert [r.key for r in found] == [
        "migros:12.09.2026:11:35:25:Filiale Muster:270:133",
        "migros:12.09.2026:09:01:00:Filiale Muster:002:84",
        "migros:05.09.2026:10:42:10:Beispiel Markt:267:14",
    ]
    first = found[0]
    assert first.when == datetime(2026, 9, 12, 11, 35, 25)
    assert first.store == "Filiale Muster"
    assert [(line.name, line.amount) for line in first.lines] == [
        ("Karotten", 1.95),
        ("Brot", 7.0),
        ("Milch", 1.95),
        ("CUMULUS BON 5.-", -5.0),
    ]
    assert first.total == 5.9
    assert found[2].total == 6.95


def test_bad_amount_names_the_line():
    text = file("12.09.2026;11:35:25;Filiale Muster;270;133;Brot;1;0.00;abc")
    with pytest.raises(HTTPException) as error:
        migros_csv.receipts(text)
    assert error.value.status_code == 400
    assert "2" in str(error.value.detail)


def test_amounts_and_times_like_the_converter():
    text = file(
        "12.09.2026;11:35:25;Filiale Muster;270;133;Velo;1;0.00;1'234.50",
        "13.09.2026;;Filiale Muster;270;134;Brot;1;0.00;3.50",
    )
    found = migros_csv.receipts(text)
    assert [(r.when, r.total) for r in found] == [
        (datetime(2026, 9, 13, 0, 0, 0), 3.5),
        (datetime(2026, 9, 12, 11, 35, 25), 1234.5),
    ]
    with pytest.raises(HTTPException):
        migros_csv.receipts(file("12.09.2026;11:35:25;Filiale Muster;270;133;Brot;1;0.00;NaN"))


def test_each_voucher_is_its_own_line():
    text = file(
        "12.09.2026;11:35:25;Filiale Muster;270;133;Brot;1;0.00;30.00",
        "12.09.2026;11:35:25;Filiale Muster;270;133;CUMULUS BON 5.-;0;0;-5.00",
        "12.09.2026;11:35:25;Filiale Muster;270;133;CUMULUS BON 5.-;0;0;-5.00",
    )
    [receipt] = migros_csv.receipts(text)
    assert [(line.name, line.amount) for line in receipt.lines] == [
        ("Brot", 30.0),
        ("CUMULUS BON 5.-", -5.0),
        ("CUMULUS BON 5.-", -5.0),
    ]
