"""Names as compared (categories, accounts, people, rule texts, articles): case and surrounding spaces don't count."""

from typing import Optional


def key(name: Optional[str]) -> str:
    return (name or "").strip().casefold()
