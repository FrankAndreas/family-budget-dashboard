"""The Migros receipt export ("Kassenbeleg", from Cumulus): every article of every receipt in a period, one per row.

A receipt is the rows with the same date, time, store, till and transaction number. Each row's "Umsatz" is what was
paid for it (after the discount in "Aktion"). Till corrections (an article cancelled and scanned again) are added up
per article; Cumulus vouchers stay as lines with a negative amount; rows of points only (amount 0) are dropped.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from . import bank_csv, messages
from .crud import to_cents

HEADER = "Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz"


def is_migros(text: str) -> bool:
    first = text.lstrip("﻿").split("\n", 1)[0].strip()
    return first.casefold() == HEADER.casefold()


def norm(name: str) -> str:
    """An article's name as compared: spaces around it and case don't count."""
    return name.strip().casefold()


@dataclass
class Line:
    name: str
    amount: float


@dataclass
class Receipt:
    key: str
    # Swiss local time, as on the receipt
    when: datetime
    store: str
    till: str = ""
    number: str = ""
    lines: list[Line] = field(default_factory=list)

    @property
    def total(self) -> float:
        return to_cents(sum(line.amount for line in self.lines))


def receipts(text: str) -> list[Receipt]:
    """The file's receipts, newest first. A row with a bad date, time or amount is a 400 naming its line."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";")
    next(reader, None)
    found: dict[str, Receipt] = {}
    # Per receipt, per article (compared by norm): the name as first written and the summed amount
    amounts: dict[str, dict[str, tuple[str, Decimal]]] = {}
    for values in reader:
        if not any(value.strip() for value in values):
            continue
        if len(values) < 9:
            raise messages.api_error(400, "migros_line_invalid", line=reader.line_num)
        day, clock, store, till, number, article, quantity, _, paid = (value.strip() for value in values[:9])
        # As the converter reads them: no time is midnight, amounts may have thousands apostrophes
        clock = clock or "00:00:00"
        amount = bank_csv.number(paid)
        try:
            when = datetime.strptime(f"{day} {clock}", "%d.%m.%Y %H:%M:%S")
        except ValueError:
            amount = None
        if amount is None:
            raise messages.api_error(400, "migros_line_invalid", line=reader.line_num)
        key = f"migros:{day}:{clock}:{store}:{till}:{number}"
        if key not in found:
            found[key] = Receipt(key=key, when=when, store=store, till=till, number=number)
            amounts[key] = {}
        # A voucher (quantity 0, an amount) is a line of its own each time; articles add up (till corrections)
        voucher = bank_csv.number(quantity) == 0 and amount != 0
        merge = f"{norm(article)}#{len(amounts[key])}" if voucher else norm(article)
        name, total = amounts[key].get(merge, (article.strip(), Decimal(0)))
        amounts[key][merge] = (name, total + amount)
    for key, receipt in found.items():
        receipt.lines = [Line(name, to_cents(float(total))) for name, total in amounts[key].values() if total != 0]
    return sorted(found.values(), key=lambda r: r.when, reverse=True)
