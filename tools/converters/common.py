"""Shared parts of the converters: reading exports, checking names against the app's schema, writing the import file."""

import csv
import io
import json
import re
import tomllib
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ZURICH = ZoneInfo("Europe/Zurich")
OUTPUT_FIELDS = (
    "date",
    "account",
    "owner",
    "category",
    "amount",
    "direction",
    "description",
    "for",
    "shared",
    "item",
    "reference",
)
MAX_TEXT = 200


class Problems(Exception):
    """Everything wrong with the config or the input; nothing is written."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def key(name) -> str:
    return str(name or "").strip().casefold()


def read_rows(path: Path, required: tuple[str, ...]) -> list[dict]:
    """The export's rows as {lower-case column: text}, each with its "_line" in the file."""
    content = Path(path).read_bytes()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") >= header.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    columns = [key(column) for column in next(reader, [])]
    missing = [column for column in required if column not in columns]
    if missing:
        raise Problems([f"missing column '{column}'" for column in missing])
    rows = []
    for values in reader:
        if any(value.strip() for value in values):
            rows.append({"_line": reader.line_num, **{c: v.strip() for c, v in zip(columns, values)}})
    return rows


def number(text: str) -> Optional[Decimal]:
    """A Swiss bank or receipt amount ("-22.1", "1'234.50"), or None if it isn't one."""
    try:
        value = Decimal(text.replace("'", "").replace("’", ""))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def money(value: Decimal) -> str:
    return f"{abs(value):.2f}"


def zurich(day: date, at: Optional[time] = None) -> str:
    """A local Swiss date (and time) as the import expects it."""
    if at is None:
        return day.isoformat()
    return datetime.combine(day, at, tzinfo=ZURICH).isoformat()


def compile_match(pattern, where: str, problems: list[str]) -> Optional[re.Pattern]:
    if not pattern:
        problems.append(f"{where}: match is required")
        return None
    try:
        return re.compile(str(pattern), re.IGNORECASE)
    except re.error:
        problems.append(f"{where}: invalid match '{pattern}'")
        return None


class Schema:
    """The names valid for the user, from the JSON Schema downloaded in the app (GET /import/schema)."""

    def __init__(self, schema: dict):
        props = schema.get("properties", {}).get("transactions", {}).get("items", {}).get("properties", {})

        def names(field):
            return {key(name): name for name in props.get(field, {}).get("enum", [])}

        self.accounts = names("account")
        self.owners = names("owner")
        self.children = names("for")
        self.splits = names("shared")
        self.items = names("item")
        self.categories = {key(name): (name, kind) for name, kind in schema.get("x-category-types", {}).items()}
        if not self.categories:
            raise Problems(["The schema has no category types; download it again from the app (Data Management)"])
        # Rules learnt in the app's import preview: (text to find, category, its type)
        self.rules: list[tuple[str, str, str]] = []
        problems = []
        for rule in schema.get("x-rules", []):
            found = self.categories.get(key(rule.get("category")))
            if not found or not rule.get("contains"):
                problems.append(f"x-rules: unknown category '{rule.get('category')}'")
                continue
            self.rules.append((key(rule["contains"]), *found))
        if problems:
            raise Problems(problems)

    @classmethod
    def load(cls, path: Path) -> "Schema":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def category(self, name, where: str, problems: list[str], kind: Optional[str] = None) -> Optional[str]:
        """The category's name as the app spells it; kind = "EXPENSE" / "INCOME" if it must be one."""
        found = self.categories.get(key(name))
        if not found:
            problems.append(f"{where}: unknown category '{name}'")
            return None
        if kind and found[1] != kind:
            label = "an expense" if kind == "EXPENSE" else "an income"
            problems.append(f"{where}: {found[0]} is not {label} category")
            return None
        return found[0]

    def kind(self, category: str) -> str:
        return self.categories[key(category)][1]

    def name(self, field: str, value, where: str, problems: list[str]) -> str:
        """An optional account/owner/child/split/item name, checked; "" if not given."""
        if not value:
            return ""
        table, label = {
            "account": (self.accounts, "account"),
            "owner": (self.owners, "owner"),
            "for": (self.children, "child"),
            "shared": (self.splits, "split"),
            "item": (self.items, "item"),
        }[field]
        if key(value) not in table:
            problems.append(f"{where}: unknown {label} '{value}'")
            return ""
        return table[key(value)]


def load_config(path: Path) -> dict:
    with open(path, "rb") as file:
        try:
            return tomllib.load(file)
        except tomllib.TOMLDecodeError as error:
            raise Problems([f"{path}: {error}"])


def output_row(**values) -> dict:
    row = {field: str(values.get(field) or "") for field in OUTPUT_FIELDS}
    row["description"] = row["description"][:MAX_TEXT]
    return row


def write_import(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}-import.csv")
