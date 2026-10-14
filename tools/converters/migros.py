"""Convert a Migros receipt export ("Kassenbeleg") into the Family Budget import format.

One row per receipt and category, booked on a Migros clearing account; see tools/converters/README.md.

    python3 tools/converters/migros.py kassenbeleg.csv --config converter.toml --schema import-schema.json
"""

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.converters import common  # noqa: E402
from tools.converters.common import Problems  # noqa: E402

COLUMNS = ("datum", "zeit", "filiale", "kassennummer", "transaktionsnummer", "artikel", "umsatz")


@dataclass
class Rule:
    match: re.Pattern
    category: str
    member: str = ""


@dataclass
class Result:
    rows: list[dict] = field(default_factory=list)
    receipts: int = 0
    skipped: list[str] = field(default_factory=list)
    totals: dict[str, float] = field(default_factory=dict)


def read_rules(raw_rules: list, table: str, schema: common.Schema, problems: list[str], children: bool) -> list[Rule]:
    rules = []
    for number, raw in enumerate(raw_rules, start=1):
        where = f"[[migros.{table}]] {number}"
        match = common.compile_match(raw.get("match"), where, problems)
        if not raw.get("category"):
            problems.append(f"{where}: category is required")
            continue
        category = schema.category(raw["category"], where, problems, "EXPENSE")
        member = schema.name("for", raw.get("for"), where, problems) if children else ""
        if match and category:
            rules.append(Rule(match, category, member))
    return rules


def convert(rows: list[dict], config: dict, schema: common.Schema) -> Result:
    config = config.get("migros", {})
    problems: list[str] = []
    if not config.get("account"):
        problems.append('[migros] give account = "<clearing account in the app>"')
    account = schema.name("account", config.get("account"), "[migros] account", problems)
    owner = schema.name("owner", config.get("owner"), "[migros] owner", problems)
    default = schema.category(
        config.get("default_category", "Groceries"), "[migros] default_category", problems, "EXPENSE"
    )
    refund = schema.category(
        config.get("refund_category", "Reimbursements"), "[migros] refund_category", problems, "INCOME"
    )
    articles = read_rules(config.get("articles", []), "articles", schema, problems, children=True)
    branches = read_rules(config.get("branches", []), "branches", schema, problems, children=False)
    if problems:
        raise Problems(problems)

    # receipt → (date and time, branch, {(category, child): sum})
    receipts: dict[tuple, dict] = {}
    for row in rows:
        line = row["_line"]
        amount = common.number(row["umsatz"])
        try:
            when = datetime.strptime(f"{row['datum']} {row['zeit'] or '00:00:00'}", "%d.%m.%Y %H:%M:%S")
        except ValueError:
            problems.append(f"line {line}: date '{row['datum']} {row['zeit']}' isn't DD.MM.YYYY HH:MM:SS")
            continue
        if amount is None:
            problems.append(f"line {line}: Umsatz '{row['umsatz']}' is not a number")
            continue
        receipt = (when.date(), row["filiale"], row["kassennummer"], row["transaktionsnummer"])
        entry = receipts.setdefault(receipt, {"when": when, "sums": defaultdict(Decimal)})
        rule = next((r for r in articles if r.match.search(row["artikel"])), None)
        rule = rule or next((r for r in branches if r.match.search(row["filiale"])), None)
        category, member = (rule.category, rule.member) if rule else (default, "")
        entry["sums"][(category, member)] += amount
    if problems:
        raise Problems(problems)

    result = Result(receipts=len(receipts))
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for (day, branch, till, number), entry in receipts.items():
        totals[day.isoformat()] += sum(entry["sums"].values(), Decimal(0))
        written = False
        for (category, member), amount in entry["sums"].items():
            if amount == 0:
                continue
            written = True
            result.rows.append(
                common.output_row(
                    date=common.zurich(entry["when"].date(), entry["when"].time()),
                    account=account,
                    owner=owner,
                    # Returns and deposit: money back, so income in the refund category
                    category=category if amount > 0 else refund,
                    amount=common.money(amount),
                    description=f"Migros {branch}",
                    reference=f"migros:{day.isoformat()}:{branch}:{till}:{number}:{category}:{member}",
                    **{"for": member if amount > 0 else ""},
                )
            )
        if not written:
            result.skipped.append(f"{day.isoformat()} {branch} {till}/{number}")
    result.totals = {day: float(total) for day, total in sorted(totals.items())}
    return result


def report(result: Result, output: Path) -> str:
    lines = [f"Wrote {len(result.rows)} rows from {result.receipts} receipts to {output}."]
    if result.skipped:
        lines.append(f"{len(result.skipped)} receipts total 0 and were skipped: " + ", ".join(result.skipped))
    lines.append("Receipt totals per day (compare with the Migros transfers from the bank):")
    lines += [f"  {day}: {total:.2f}" for day, total in result.totals.items()]
    lines.append("Converting again after changing the rules gives new references: those receipts aren't recognised")
    lines.append("as already imported.")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Migros receipt export into the Family Budget import format."
    )
    parser.add_argument("export", type=Path, help="the Migros Kassenbeleg CSV export")
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
