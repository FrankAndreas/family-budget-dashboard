"""Asking about spending in plain words (design 2026-11-27).

The AI only turns the question into a query: income or expenses, one category or tag (or all), a range of whole
months, and whether to compare with the same number of months before. Its answer is untrusted: names must be the
family's own, the months valid; otherwise the question is "unclear", never guessed. The amounts come from
reports.lines, so they match the Analytics tab. The prompt holds only the question, the category and tag names and
today's date.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from . import i18n, models, reports
from .money import cents

ASK_MARKER = "QUESTION:"
MAX_QUESTION = 300
MAX_MONTHS = 120
MONTH = re.compile(r"^(\d{4})-(\d{2})$")
KINDS = {"expense": models.CategoryType.EXPENSE, "income": models.CategoryType.INCOME}

SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["expense", "income", "unknown"]},
        "category": {"type": ["string", "null"]},
        "tag": {"type": ["string", "null"]},
        "from": {"type": "string"},
        "to": {"type": "string"},
        "compare": {"type": "boolean"},
    },
    "required": ["kind", "category", "tag", "from", "to", "compare"],
    "additionalProperties": False,
}

PROMPTS = {
    "de": """Du übersetzt eine Frage zu den Finanzen einer Familie in eine Abfrage. Heute ist {today}.
Gib NUR JSON zurück, in genau diesem Format:
{{"kind": "expense", "category": null, "tag": null, "from": "YYYY-MM", "to": "YYYY-MM", "compare": false}}
Regeln:
- kind: "expense" für Ausgaben, "income" für Einnahmen, "unknown" wenn die Frage keine Summe von Ausgaben oder
  Einnahmen über einen Zeitraum ist.
- category: genau einer dieser Namen oder null für alle: {categories}
- tag: genau einer dieser Namen oder null; nie category und tag zusammen: {tags}
- from und to: der erste und der letzte Monat des Zeitraums (beide inklusive). "Diesen Monat" ist {month}; ohne
  Zeitraum in der Frage gilt dieser Monat.
- compare: true, wenn mit dem Zeitraum davor verglichen werden soll.
""",
    "en": """You turn a question about a family's finances into a query. Today is {today}.
Return ONLY JSON, in exactly this format:
{{"kind": "expense", "category": null, "tag": null, "from": "YYYY-MM", "to": "YYYY-MM", "compare": false}}
Rules:
- kind: "expense" for spending, "income" for income, "unknown" if the question is not a sum of spending or income over
  a period.
- category: exactly one of these names, or null for all: {categories}
- tag: exactly one of these names, or null; never category and tag together: {tags}
- from and to: the first and the last month of the period (both included). "This month" is {month}; with no period
  in the question, use this month.
- compare: true if it should be compared with the period before.
""",
}


@dataclass(frozen=True)
class Query:
    kind: models.CategoryType
    category: Optional[models.Category]
    tag: Optional[models.Tag]
    first: date
    last: date
    compare: bool


def prompt(question: str, categories: list[str], tags: list[str], today: date, language: str) -> str:
    template = PROMPTS.get(language, PROMPTS["en"])
    text = template.format(
        today=today.isoformat(),
        month=today.strftime("%Y-%m"),
        categories=json.dumps(categories, ensure_ascii=False),
        tags=json.dumps(tags, ensure_ascii=False),
    )
    return text + ASK_MARKER + question


def month(value: object) -> Optional[date]:
    match = MONTH.match(value) if isinstance(value, str) else None
    if not match or not 1 <= int(match.group(2)) <= 12:
        return None
    return date(int(match.group(1)), int(match.group(2)), 1)


def months_between(first: date, last: date) -> int:
    return (last.year - first.year) * 12 + last.month - first.month + 1


def parse(answer: str, db: Session, today: date) -> Optional[Query]:
    """The checked query, or None when the answer can't be trusted to mean one (unknown name, bad months, ...)."""
    match = re.search(r"\{.*\}", answer, re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        return None
    kind = KINDS[data["kind"]]
    category_name, tag_name = data.get("category"), data.get("tag")
    if category_name is not None and tag_name is not None:
        return None
    category = tag = None
    if category_name is not None:
        wanted = str(category_name).casefold()
        category = next(
            (c for c in db.query(models.Category) if wanted in {n.casefold() for n in i18n.all_names(c) if n}), None
        )
        if category is None or category.type != kind:
            return None
    if tag_name is not None:
        wanted = str(tag_name).casefold()
        tag = next((t for t in db.query(models.Tag) if t.name.casefold() == wanted), None)
        if tag is None:
            return None
    first, last = month(data.get("from")), month(data.get("to"))
    if first is None or last is None or last < first or months_between(first, last) > MAX_MONTHS:
        return None
    # Months still to come have no bookings: a sum of 0 would be a wrong answer, not a known one
    if first > today.replace(day=1):
        return None
    return Query(kind, category, tag, first, last, data.get("compare") is True)


def next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def total(db: Session, owner_id: str, query: Query, first: date, last: date) -> float:
    """The owner's income or expenses from the month `first` through the month `last`, as on the Analytics tab."""
    amount = 0.0
    for line in reports.lines(db, owner_id, first, next_month(last)):
        if line.type != query.kind:
            continue
        if query.category is not None and line.category.id != query.category.id:
            continue
        if query.tag is not None and query.tag.id not in line.tag_ids:
            continue
        amount += line.amount
    return cents(amount)


def previous(query: Query) -> tuple[date, date]:
    """The same number of months right before the query's."""
    count = months_between(query.first, query.last)
    index = query.first.year * 12 + query.first.month - 1 - count
    first = date(index // 12, index % 12 + 1, 1)
    end = query.first.year * 12 + query.first.month - 2
    return first, date(end // 12, end % 12 + 1, 1)
