"""IBANs of accounts (bank import): stored compact and uppercase, checked by the ISO 13616 checksum."""

import re

SHAPE = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def is_valid(value: str) -> bool:
    iban = compact(value)
    if not SHAPE.fullmatch(iban):
        return False
    # Country and check digits move to the end; letters become 10..35; the number mod 97 must be 1
    moved = iban[4:] + iban[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def grouped(value: str) -> str:
    iban = compact(value)
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))
