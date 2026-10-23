"""A bank account's CSV export (Raiffeisen: IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date) as import rows.

Each line becomes an ordinary import row: the account is found by its IBAN in the import (import_api.check_file),
the category starts as the fallback (Unsorted / Other Income) for rules and the AI to replace. The text cleaning and
the reference are the same as in tools/converters/bank.py, so a converted file and the raw one are the same rows.
"""

import csv
import hashlib
import io
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from zoneinfo import ZoneInfo

from . import ibans

COLUMNS = ("iban", "booked at", "text", "credit/debit amount")
ZURICH = ZoneInfo("Europe/Zurich")
# The seed's names of the fallbacks, which the import's category lookup knows in every language
FALLBACK_OUT, FALLBACK_IN = "Unsorted", "Other Income"
MAX_TEXT = 200

# "Einkauf <merchant> 06.09.2026, 08:45, Debit Mastercard-Nr. 123456xxxxxx1234"
CARD = re.compile(
    r"^(?P<prefix>Einkauf) (?P<merchant>.+?) (?P<day>\d{2}\.\d{2}\.\d{4}), (?P<time>\d{2}:\d{2}),?"
    r"(?: [\w -]*?-Nr\. ?\S*)?$"
)
CARD_NUMBER = re.compile(r",? *(?:Debit )?[\w-]*-Nr\. ?\S*")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
SPACES = re.compile(r"\s+")


def key(name: str) -> str:
    return (name or "").strip().casefold()


def is_bank(text: str) -> bool:
    header = [key(column) for column in text.split("\n", 1)[0].split(";")]
    return all(column in header for column in COLUMNS)


def decode(content: bytes) -> Optional[str]:
    """The file as text: UTF-8 (with or without BOM), or Windows-1252 for a bank export; None if neither."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
        return text if is_bank(text) else None


def clean(text: str) -> tuple[str, Optional[tuple[date, time]]]:
    """(description, purchase date and time of a card line): card numbers and IBANs never reach the app."""
    card = CARD.match(text)
    if card:
        when = (
            datetime.strptime(card["day"], "%d.%m.%Y").date(),
            datetime.strptime(card["time"], "%H:%M").time(),
        )
        return SPACES.sub(" ", card["merchant"]).strip(), when
    return SPACES.sub(" ", IBAN.sub("", CARD_NUMBER.sub("", text))).strip(), None


def number(text: str) -> Optional[Decimal]:
    try:
        value = Decimal(text.replace("'", "").replace("’", ""))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def booked_day(value: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(value.split(" ")[0]).date()
    except ValueError:
        return None


def rows(text: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """One import row per line ({"_line", every field}), plus _iban (compact), _booked (date or None), _balance
    (float or None) and _skip (amount 0). Values that can't be read stay as they are, for the import to report."""
    reader = csv.reader(io.StringIO(text), delimiter=";")
    columns = [key(column) for column in next(reader, [])]
    out = []
    for values in reader:
        if not any(value.strip() for value in values):
            continue
        raw = {c: v.strip() for c, v in zip(columns, values)}
        get = lambda name: raw.get(name, "")  # noqa: E731
        amount = number(get("credit/debit amount"))
        day = booked_day(get("booked at"))
        description, when = clean(get("text"))
        if when:
            when_text = datetime.combine(*when, tzinfo=ZURICH).isoformat()
        else:
            when_text = day.isoformat() if day else get("booked at")
        digest = "|".join([get("iban"), get("booked at"), get("text"), get("credit/debit amount"), get("balance")])
        balance = number(get("balance"))
        row = {field: "" for field in fields}
        row.update(
            date=when_text,
            amount=f"{abs(amount):.2f}" if amount is not None else get("credit/debit amount"),
            category=FALLBACK_IN if amount is not None and amount > 0 else FALLBACK_OUT,
            description=description[:MAX_TEXT],
            reference="bank:" + hashlib.sha256(digest.encode("utf-8")).hexdigest()[:16],
        )
        out.append(
            {
                "_line": reader.line_num,
                **row,
                "_iban": ibans.compact(get("iban")),
                "_booked": day,
                "_balance": float(balance) if balance is not None else None,
                "_skip": amount == 0,
            }
        )
    return out
