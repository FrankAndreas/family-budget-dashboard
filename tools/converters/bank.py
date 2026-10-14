"""Convert a bank account's CSV export into the Family Budget import format, using rules from converter.toml.

    python3 tools/converters/bank.py export.csv --config converter.toml --schema import-schema.json

See tools/converters/README.md.
"""

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.converters import common  # noqa: E402
from tools.converters.common import Problems, key  # noqa: E402

COLUMNS = ("iban", "booked at", "text", "credit/debit amount", "balance")
ACTIONS = ("book", "transfer", "ignore")
TRANSFER = "Transfer"

# "Einkauf <merchant> 06.09.2026, 08:45, Debit Mastercard-Nr. 123456xxxxxx1234"
CARD = re.compile(
    r"^(?P<prefix>Einkauf) (?P<merchant>.+?) (?P<day>\d{2}\.\d{2}\.\d{4}), (?P<time>\d{2}:\d{2}),?"
    r"(?: [\w -]*?-Nr\. ?\S*)?$"
)
CARD_NUMBER = re.compile(r",? *(?:Debit )?[\w-]*-Nr\. ?\S*")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
SPACES = re.compile(r"\s+")


@dataclass
class Rule:
    number: int
    match: re.Pattern
    action: str
    category: str = ""
    sign: str = ""  # "debit", "credit", or "" for both
    description: str = ""
    item: str = ""
    member: str = ""
    shared: str = ""
    # A transfer to an account without its own export (e.g. a clearing account): the converter books its side too
    to_account: str = ""
    to_owner: str = ""

    def applies(self, debit: bool) -> bool:
        return not self.sign or self.sign == ("debit" if debit else "credit")


@dataclass
class Result:
    rows: list[dict] = field(default_factory=list)
    booked: int = 0
    transfers: int = 0
    ignored: list[tuple[int, str, float]] = field(default_factory=list)
    unrecognised: list[tuple[int, str, float]] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)
    balance: Optional[tuple[str, float]] = None


def compact_iban(value: str) -> str:
    return value.replace(" ", "").upper()


def read_rules(config: dict, schema: common.Schema, problems: list[str], exported: set[str]) -> list[Rule]:
    rules = []
    for number, raw in enumerate(config.get("rules", []), start=1):
        where = f"rule {number}"
        match = common.compile_match(raw.get("match"), where, problems)
        action = key(raw.get("action") or "book")
        if action not in ACTIONS:
            problems.append(f"{where}: action must be book, transfer or ignore")
            continue
        sign = key(raw.get("sign"))
        if sign not in ("", "debit", "credit"):
            problems.append(f"{where}: sign must be debit or credit")
        rule = Rule(number, match, action, sign=sign, description=str(raw.get("description") or ""))
        if raw.get("to_account") and action != "transfer":
            problems.append(f"{where}: to_account is only for transfers")
        elif raw.get("to_account"):
            rule.to_account = schema.name("account", raw["to_account"], where, problems)
            rule.to_owner = schema.name("owner", raw.get("to_owner"), where, problems)
            if key(rule.to_account) in exported:
                problems.append(f"{where}: to_account is the account of the export")
        if action == "book":
            if not raw.get("category"):
                problems.append(f"{where}: category is required (or action = transfer / ignore)")
                continue
            if key(raw["category"]) == key(TRANSFER):
                problems.append(f"{where}: use action = transfer instead of the category Transfer")
                continue
            rule.category = schema.category(raw["category"], where, problems) or ""
            kind = schema.kind(rule.category) if rule.category else ""
            # A booking rule only catches lines whose sign fits its category
            fits = "debit" if kind == "EXPENSE" else "credit"
            if kind == "TRANSFER":
                problems.append(f"{where}: use action = transfer instead of the category {rule.category}")
            elif kind and sign and sign != fits:
                label = "an expense" if kind == "EXPENSE" else "income"
                problems.append(f"{where}: {rule.category} is {label} but sign is {sign}")
            elif kind:
                rule.sign = fits
            rule.item = schema.name("item", raw.get("item"), where, problems)
            rule.member = schema.name("for", raw.get("for"), where, problems)
            rule.shared = schema.name("shared", raw.get("shared"), where, problems)
        if match:
            rules.append(rule)
    return rules


def read_accounts(config: dict, schema: common.Schema, problems: list[str]) -> dict[str, tuple[str, str]]:
    accounts = {}
    for iban, target in config.get("accounts", {}).items():
        where = f"[bank.accounts] {compact_iban(iban)}"
        if not isinstance(target, dict) or not target.get("account"):
            problems.append(f'{where}: give account = "<name in the app>"')
            continue
        account = schema.name("account", target["account"], where, problems)
        owner = schema.name("owner", target.get("owner"), where, problems)
        accounts[compact_iban(iban)] = (account, owner)
    return accounts


def clean(text: str) -> tuple[str, str, Optional[tuple[date, time]]]:
    """(text for matching, description, purchase date and time from a card line)."""
    card = CARD.match(text)
    if card:
        when = (
            datetime.strptime(card["day"], "%d.%m.%Y").date(),
            datetime.strptime(card["time"], "%H:%M").time(),
        )
        merchant = SPACES.sub(" ", card["merchant"]).strip()
        return f"{card['prefix']} {merchant}", merchant, when
    text = IBAN.sub("", CARD_NUMBER.sub("", text))
    text = SPACES.sub(" ", text).strip()
    return text, text, None


def booked_day(value: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(value.split(" ")[0]).date()
    except ValueError:
        return None


def convert(rows: list[dict], config: dict, schema: common.Schema) -> Result:
    config = config.get("bank", {})
    problems: list[str] = []
    accounts = read_accounts(config, schema, problems)
    fallback = config.get("fallback", {})
    fallback_expense = schema.category(
        fallback.get("expense", "Unsorted"), "[bank.fallback] expense", problems, "EXPENSE"
    )
    fallback_income = schema.category(
        fallback.get("income", "Other Income"), "[bank.fallback] income", problems, "INCOME"
    )
    transfer = schema.category(TRANSFER, "Transfer", problems)
    rules = read_rules(config, schema, problems, {key(account) for account, _ in accounts.values()})
    if problems:
        raise Problems(problems)

    result = Result()
    latest: Optional[tuple[date, int, str]] = None
    for row in rows:
        line = row["_line"]
        iban = compact_iban(row["iban"])
        amount = common.number(row["credit/debit amount"])
        day = booked_day(row["booked at"])
        if iban not in accounts:
            problems.append(f"line {line}: IBAN {iban} is not in [bank.accounts]")
        if amount is None:
            problems.append(f"line {line}: amount '{row['credit/debit amount']}' is not a number")
        if day is None:
            problems.append(f"line {line}: date '{row['booked at']}' is not a date")
        if problems and (iban not in accounts or amount is None or day is None):
            continue

        balance = common.number(row.get("balance", ""))
        if balance is not None and (latest is None or day > latest[0]):
            latest = (day, line, f"{balance:.2f}")

        text, description, when = clean(row["text"])
        if amount == 0:
            result.skipped.append((line, text))
            continue
        debit = amount < 0
        rule = next((r for r in rules if r.applies(debit) and r.match.search(text)), None)
        if rule and rule.action == "ignore":
            result.ignored.append((line, text, float(amount)))
            continue
        if not rule:
            result.unrecognised.append((line, text, float(amount)))

        account, owner = accounts[iban]
        digest = "|".join([row["iban"], row["booked at"], row["text"], row["credit/debit amount"], row["balance"]])
        values = dict(
            date=common.zurich(*when) if when else common.zurich(day),
            account=account,
            owner=owner,
            amount=common.money(amount),
            description=(rule.description if rule and rule.description else description),
            reference="bank:" + hashlib.sha256(digest.encode("utf-8")).hexdigest()[:16],
        )
        if rule and rule.action == "transfer":
            values.update(category=transfer, direction="out" if debit else "in")
            result.transfers += 1
            if rule.to_account:
                result.rows.append(common.output_row(**values))
                values.update(
                    account=rule.to_account,
                    owner=rule.to_owner,
                    direction="in" if debit else "out",
                    reference=values["reference"] + ":to",
                )
        elif rule:
            values.update(category=rule.category, item=rule.item, shared=rule.shared, **{"for": rule.member})
            result.booked += 1
        else:
            values.update(category=fallback_expense if debit else fallback_income)
            result.booked += 1
        result.rows.append(common.output_row(**values))

    if problems:
        raise Problems(problems)
    if latest:
        result.balance = (latest[0].isoformat(), float(latest[2]))
    return result


def report(result: Result, output: Path) -> str:
    lines = [
        f"Wrote {len(result.rows)} rows to {output}: {result.booked} booked, {result.transfers} transfers;"
        f" {len(result.ignored)} ignored, {len(result.skipped)} skipped (amount 0).",
    ]
    if result.unrecognised:
        lines.append(f"{len(result.unrecognised)} lines not recognised (fallback category; add a rule):")
        lines += [f"  line {line}: {amount:>10.2f}  {text}" for line, text, amount in result.unrecognised]
    if result.balance:
        day, balance = result.balance
        lines.append(f"Bank balance on {day}: {balance:.2f} (compare with the account in the app after importing)")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a bank CSV export into the Family Budget import format.")
    parser.add_argument("export", type=Path, help="the bank's CSV export")
    parser.add_argument("--config", type=Path, required=True, help="converter.toml")
    parser.add_argument("--schema", type=Path, required=True, help="JSON Schema downloaded from the app")
    parser.add_argument("--output", type=Path, help="default: <export>-import.csv")
    args = parser.parse_args(argv)
    output = args.output or common.output_path(args.export)
    try:
        result = convert(
            common.read_rows(args.export, COLUMNS), common.load_config(args.config), common.Schema.load(args.schema)
        )
    except Problems as error:
        print("Nothing written:")
        print("\n".join(f"  {problem}" for problem in error.problems))
        return 1
    common.write_import(output, result.rows)
    print(report(result, output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
