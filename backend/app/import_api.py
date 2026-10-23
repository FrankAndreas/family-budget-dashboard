"""Bulk import of transactions from a CSV or JSON file written by an external tool (e.g. a receipt reader).

Rows name accounts, categories, children, splits and investments; they are resolved like the form would,
checked row by row for a preview, and booked together or not at all.
"""

import csv
import io
import json
import math
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from . import auth, bank_csv, crud, database, i18n, ibans, import_rules, models, privacy, schemas, messages
from .api import check_asset, check_member_tag, check_shared, is_dependent
from .common_api import visible_owner
from .seed import SETTLE_UP

router = APIRouter()

MAX_BYTES = 1024 * 1024
MAX_ROWS = 1000
MAX_TEXT = 200
FIELDS = (
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
DIRECTIONS = {"in": 1, "out": -1}
DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")

TEMPLATE = (
    "date,account,category,amount,description,for,shared,item,reference\n"
    "2026-10-12,Bank,Groceries,84.30,Migros,,Equal 50/50,,receipt-0001.jpg\n"
    "2026-10-13,Bank,Healthcare,120.00,Dentist,Timmy,,,receipt-0002.jpg\n"
)


def key(name: str) -> str:
    """Names match ignoring upper/lower case and surrounding spaces."""
    return name.strip().casefold()


def categories_by_name(db: Session) -> dict[str, models.Category]:
    """Categories by key(name); the 🔒 ones under their stored name and their name in every language."""
    return {key(name): c for c in db.query(models.Category) for name in i18n.all_names(c)}


def text_value(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_file(filename: str, content: bytes) -> tuple[list[dict[str, Any]], bool]:
    """The file's rows as {field: text}, each with its "_line" (CSV line, or position in the JSON list); and whether
    it is a bank account's export (bank_csv.py)."""
    if len(content) > MAX_BYTES:
        raise messages.api_error(400, "file_too_large")
    text = bank_csv.decode(content)
    if text is None:
        raise messages.api_error(400, "file_not_utf8")

    bank = bank_csv.is_bank(text)
    if bank:
        rows = bank_csv.rows(text, FIELDS)
    elif filename.lower().endswith(".json") or text.lstrip().startswith(("{", "[")):
        rows = parse_json(text)
    else:
        rows = parse_csv(text)
    if not rows:
        raise messages.api_error(400, "file_empty")
    if len(rows) > MAX_ROWS:
        raise messages.api_error(400, "max_rows", count=MAX_ROWS)
    return rows, bank


def parse_json(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise messages.api_error(400, "json_invalid", error=error.msg, line=error.lineno)
    items = data.get("transactions") if isinstance(data, dict) else data
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise messages.api_error(400, "json_shape")
    return [
        {"_line": index, **{field: text_value(item.get(field)) for field in FIELDS}}
        for index, item in enumerate(items, start=1)
    ]


def parse_csv(text: str) -> list[dict[str, Any]]:
    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        columns = [key(column) for column in next(reader)]
    except StopIteration:
        return []
    rows = []
    for values in reader:
        if not any(value.strip() for value in values):
            continue
        row = dict(zip(columns, values))
        rows.append({"_line": reader.line_num, **{field: text_value(row.get(field)) for field in FIELDS}})
    return rows


def parse_date(value: str) -> datetime:
    # A date alone is booked at noon UTC, so it stays on that day in Switzerland
    if DATE_ONLY.fullmatch(value):
        return datetime.fromisoformat(value).replace(hour=12)
    return crud.to_naive_utc(datetime.fromisoformat(value))


class Lookups:
    """Everything a row's names can refer to, for the current user."""

    def __init__(self, db: Session, user: models.User):
        users = db.query(models.User).all()
        self.names = {u.id: u.username for u in users}
        levels = {u.id: privacy.access_level(db, user, u) for u in users}
        accounts = db.query(models.Account).all()
        self.user_id = user.id
        self.writable = [a for a in accounts if privacy.can_write(levels.get(a.user_id))]
        self.view_only = [a for a in accounts if levels.get(a.user_id) == "VIEW"]
        self.categories = categories_by_name(db)
        self.children = {key(u.username): u for u in users if is_dependent(u) and levels.get(u.id)}
        is_parent = user.role == models.UserRole.PARENT
        self.splits = {key(s.name): s for s in db.query(models.Split)} if is_parent else {}
        self.assets = {
            key(a.name): a
            for a in db.query(models.Asset)
            if is_parent and visible_owner(db, user, a.owner_id, a.split_id)
        }

        visible = [a.id for a in accounts if levels.get(a.user_id)]
        existing = db.query(models.Transaction).filter(models.Transaction.account_id.in_(visible)).all()
        self.references = {t.reference: t for t in existing if t.reference}
        self.bookings = {(t.account_id, t.date.date(), t.amount, t.category_id): t for t in existing}

    def account(self, name: str, owner: str) -> tuple[Optional[models.Account], Optional[str]]:
        matches = [a for a in self.writable if key(a.name or "") == key(name)]
        if owner:
            matches = [a for a in matches if key(self.names.get(a.user_id, "")) == key(owner)]
        elif len(matches) > 1:
            matches = [a for a in matches if a.user_id == self.user_id] or matches
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, messages.text("several_accounts", name=name)
        if any(key(a.name or "") == key(name) for a in self.view_only):
            return None, messages.text("account_view_only", name=name)
        return None, (
            messages.text("unknown_account_of", name=name, owner=owner)
            if owner
            else messages.text("unknown_account", name=name)
        )


def check_row(db: Session, user: models.User, lookups: Lookups, raw: dict, seen: dict[str, int]) -> dict:
    # A bank line found its account by IBAN already (or carries why it didn't)
    errors: list[str] = list(raw.get("_errors", []))
    row = {field: raw[field] for field in FIELDS}
    out = {"line": raw["_line"], "status": "ok", "errors": errors, "duplicate_of": None, "note": None, **row}

    date = None
    if not row["date"]:
        errors.append(messages.text("date_required"))
    else:
        try:
            date = parse_date(row["date"])
        except ValueError:
            errors.append(messages.text("date_format", date=row["date"]))

    amount = None
    try:
        amount = float(row["amount"])
    except ValueError:
        errors.append(
            messages.text("amount_required")
            if not row["amount"]
            else messages.text("amount_format", amount=row["amount"])
        )
    if amount is not None and (not math.isfinite(amount) or amount <= 0):
        errors.append(messages.text("amount_positive"))
        amount = None

    account: Optional[models.Account]
    if "_iban" in raw:
        account, problem = raw.get("_account"), None
    elif not row["account"]:
        account, problem = None, messages.text("account_required")
    else:
        account, problem = lookups.account(row["account"], row["owner"])
    if problem:
        errors.append(problem)

    category = lookups.categories.get(key(row["category"]))
    if not row["category"]:
        errors.append(messages.text("category_required"))
    elif not category:
        errors.append(messages.text("unknown_category", name=row["category"]))
    else:
        # The name of the person's language, so the preview matches the category list
        row["category"] = out["category"] = i18n.category_name(category)
    if category is not None and category.system_key == SETTLE_UP:
        errors.append(messages.text("settle_up_not_importable"))
        category = None

    # A transfer has no income/expense type to take the sign from, so the row says which way the money went
    is_transfer = category is not None and category.type == models.CategoryType.TRANSFER
    direction = key(row["direction"])
    if is_transfer and not direction:
        errors.append(messages.text("direction_required"))
    elif direction and direction not in DIRECTIONS:
        errors.append(messages.text("direction_format", direction=row["direction"]))
    elif direction and category is not None and not is_transfer:
        errors.append(messages.text("direction_transfers_only"))
    if is_transfer and (row["for"] or row["shared"] or row["item"]):
        errors.append(messages.text("transfer_plain_only"))

    member = split = asset = None
    if row["for"]:
        member = lookups.children.get(key(row["for"]))
        if not member:
            errors.append(messages.text("unknown_child", name=row["for"]))
    if row["shared"]:
        split = lookups.splits.get(key(row["shared"]))
        if not split:
            errors.append(messages.text("unknown_split", name=row["shared"]))
    if row["item"]:
        asset = lookups.assets.get(key(row["item"]))
        if not asset:
            errors.append(messages.text("unknown_investment", name=row["item"]))
    for field in ("description", "reference"):
        if len(row[field]) > MAX_TEXT:
            errors.append(messages.text("text_too_long", field=field, count=MAX_TEXT))

    split_shares = None
    if account and category:
        try:
            check_member_tag(db, member.id if member else None, account.id)
            split_shares = check_shared(db, split.id if split else None, account.id, category)
            check_asset(db, user, asset.id if asset else None)
        except HTTPException as error:
            errors.append(str(error.detail))

    if errors:
        out["status"] = "error"
        return out
    # Without errors every value was found (this tells the type checker so)
    assert account is not None and category is not None and date is not None and amount is not None

    if is_transfer:
        amount = amount * DIRECTIONS[direction]
    signed = crud.signed_amount(amount, category)
    reference = row["reference"] or None
    if reference and reference in lookups.references:
        twin = lookups.references[reference]
        out.update(
            status="duplicate",
            duplicate_of=twin.id,
            note=messages.text("duplicate_reference_booked", date=twin.date.date()),
        )
    elif reference and reference in seen:
        out.update(status="duplicate", note=messages.text("duplicate_reference_line", line=seen[reference]))
    elif (account.id, date.date(), signed, category.id) in lookups.bookings:
        twin = lookups.bookings[(account.id, date.date(), signed, category.id)]
        out.update(
            status="duplicate", duplicate_of=twin.id, note=messages.text("duplicate_booked", date=twin.date.date())
        )
    if reference:
        seen.setdefault(reference, raw["_line"])

    out["_create"] = (
        schemas.TransactionCreate(
            account_id=account.id,
            category_id=category.id,
            amount=amount,
            description=row["description"] or None,
            date=date,
            member_id=member.id if member else None,
            split_id=split.id if split else None,
            asset_id=asset.id if asset else None,
            reference=reference,
        ),
        category,
        split_shares,
    )
    return out


def find_accounts(lookups: Lookups, raw_rows: list[dict]) -> None:
    """A bank line's account is the writable one with its IBAN; without one the line says so."""
    by_iban = {a.iban: a for a in lookups.writable if a.iban}
    for raw in raw_rows:
        account = by_iban.get(raw["_iban"])
        if account:
            raw.update(_account=account, account=account.name or "", owner=lookups.names.get(account.user_id, ""))
        else:
            raw["_errors"] = [messages.text("no_account_for_iban", iban=ibans.grouped(raw["_iban"]))]


def skipped(raw: dict) -> dict:
    """A bank line with amount 0 (e.g. a closing without interest): shown, never booked."""
    fields = {field: raw[field] for field in FIELDS}
    note = messages.text("bank_zero_amount")
    return {"line": raw["_line"], "status": "skipped", "errors": [], "duplicate_of": None, "note": note, **fields}


def source(raw: dict, change: Optional[dict], rule: Optional[str]) -> Optional[str]:
    """Where a bank row's category came from; None for other files."""
    if "_iban" not in raw:
        return None
    if change:
        return "ai" if change.get("source") == "ai" else "change"
    return "rule" if rule else "fallback"


def check_file(
    db: Session, user: models.User, file: UploadFile, changes: Optional[dict] = None
) -> tuple[list[dict], bool]:
    """The checked rows, and whether the file is a bank export."""
    raw_rows, bank = parse_file(file.filename or "", file.file.read(MAX_BYTES + 1))
    if bank and user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_import_bank")
    changes = changes or {}
    unknown = set(changes) - {raw["_line"] for raw in raw_rows}
    if unknown:
        raise messages.api_error(400, "changes_unknown_line", line=min(unknown))
    if any(c.get("remember") for c in changes.values()):
        import_rules.require_parent(user)
    lookups = Lookups(db, user)
    if bank:
        find_accounts(lookups, raw_rows)
    rules = import_rules.load(db)
    seen: dict[str, int] = {}
    rows = []
    for raw in raw_rows:
        if raw.get("_skip"):
            rows.append({**skipped(raw), "file_category": raw["category"], "rule": None, "source": None})
            continue
        change = changes.get(raw["_line"])
        adjusted, problem, rule = import_rules.adjust(raw, change, lookups, rules)
        out = check_row(db, user, lookups, adjusted, seen)
        # Any non-empty text is checked, so "   " is an error rather than silently ignored
        remember = (change or {}).get("remember") or ""
        problems = [problem, import_rules.remember_problem(remember) if remember else None]
        for text in filter(None, problems):
            out["errors"].append(text)
            out["status"] = "error"
        # The file's category by its name in the person's language when known, like the category list
        known = lookups.categories.get(key(raw["category"]))
        out.update(
            file_category=i18n.category_name(known) if known else raw["category"],
            rule=rule,
            source=source(raw, change, rule),
            _account=raw.get("_account"),
            _booked=raw.get("_booked"),
            _balance=raw.get("_balance"),
        )
        rows.append(out)
    return rows, bank


def balances(rows: list[dict]) -> list[dict]:
    """Per account in a bank file: the balance of its latest line, next to the app's after booking the ok rows."""
    latest: dict[str, tuple] = {}
    added: dict[str, float] = {}
    for row in rows:
        account = row.get("_account")
        if account is None:
            continue
        if row.get("_balance") is not None and row.get("_booked"):
            when = (row["_booked"], row["line"])
            if account.id not in latest or when > latest[account.id][0]:
                latest[account.id] = (when, row["_balance"])
        if row["status"] == "ok":
            transaction, category, _ = row["_create"]
            added[account.id] = added.get(account.id, 0.0) + crud.signed_amount(transaction.amount, category)
    accounts = {row["_account"].id: row["_account"] for row in rows if row.get("_account") is not None}
    return [
        {
            "account_id": account.id,
            "account": account.name,
            "file_balance": latest[account.id][1] if account.id in latest else None,
            "app_balance": round((account.balance or 0) + added.get(account.id, 0.0), 2),
        }
        for account in accounts.values()
    ]


def public(rows: list[dict], bank: bool = False) -> dict:
    statuses = ("ok", "duplicate", "error", "skipped")
    counts = {status: sum(r["status"] == status for r in rows) for status in statuses}
    result = {
        "rows": [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows],
        "ok": counts["ok"],
        "duplicates": counts["duplicate"],
        "errors": counts["error"],
        "skipped": counts["skipped"],
    }
    if bank:
        result["balances"] = balances(rows)
    return result


@router.post("/import/preview")
def preview_import(
    file: UploadFile = File(...),
    changes: str = Form(""),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return public(*check_file(db, current_user, file, import_rules.parse_changes(changes)))


@router.post("/import")
def run_import(
    file: UploadFile = File(...),
    include_duplicates: str = Form(""),
    changes: str = Form(""),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    changed = import_rules.parse_changes(changes)
    rows, bank = check_file(db, current_user, file, changed)
    if any(row["status"] == "error" for row in rows):
        raise HTTPException(status_code=400, detail={"message": messages.text("file_has_errors"), **public(rows, bank)})
    included = {int(line) for line in include_duplicates.split(",") if line.strip().isdigit()}
    chosen = [row for row in rows if row["status"] == "ok" or row["line"] in included]
    try:
        for row in chosen:
            transaction, category, split_shares = row["_create"]
            crud.create_transaction(db, transaction, category, split_shares=split_shares, commit=False)
        # Remembered rules are saved with the bookings, so a failed import saves none
        categories = categories_by_name(db)
        for row in rows:
            text = changed.get(row["line"], {}).get("remember")
            if text:
                category = categories[key(row["category"])]
                import_rules.remember(db, text, category)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"imported": len(chosen), "skipped": len(rows) - len(chosen)}


@router.get("/import/schema")
def import_schema(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    """A JSON Schema of the import file for this user, listing the names that are valid for them."""
    lookups = Lookups(db, current_user)
    # Each category once (lookups know the 🔒 ones under several names); the schema uses the stored names
    importable = [c for c in {c.id: c for c in lookups.categories.values()}.values() if c.system_key != SETTLE_UP]

    def unique(names) -> list[str]:
        return sorted(set(names), key=str.casefold)

    properties: dict[str, dict] = {
        "date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}(T.+)?$",
            "description": "Date of the purchase, YYYY-MM-DD (or ISO 8601 with time and offset)",
        },
        "account": {
            "type": "string",
            "enum": unique(a.name for a in lookups.writable),
            "description": "The account the money left (or arrived on)",
        },
        "owner": {
            "type": "string",
            "enum": unique(lookups.names[a.user_id] for a in lookups.writable),
            "description": "Whose account it is; only needed when two accounts have the same name",
        },
        "category": {
            "type": "string",
            "enum": unique(c.name for c in importable),
            "description": "Category; it decides whether this is income or an expense (Transfer: see direction)",
        },
        "amount": {"type": "number", "exclusiveMinimum": 0, "description": "Amount in CHF, always positive"},
        "direction": {
            "type": "string",
            "enum": ["in", "out"],
            "description": "Only for the category Transfer: out = money leaves this account, in = it arrives",
        },
        "description": {"type": "string", "maxLength": MAX_TEXT, "description": "Shop or what was bought"},
        "for": {
            "type": "string",
            "enum": unique(u.username for u in lookups.children.values()),
            "description": "The child this expense was for",
        },
        "shared": {
            "type": "string",
            "enum": unique(s.name for s in lookups.splits.values()),
            "description": "Split, if the cost is shared between the parents",
        },
        "item": {
            "type": "string",
            "enum": unique(a.name for a in lookups.assets.values()),
            "description": "The investment this expense belongs to (purchase, repair, service)",
        },
        "reference": {
            "type": "string",
            "maxLength": MAX_TEXT,
            "description": "Your own ID for the source, e.g. the receipt's file name; recognises repeated imports",
        },
    }
    # A field with nothing to choose from can't be used at all
    properties = {name: prop for name, prop in properties.items() if prop.get("enum", True)}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Family Budget transaction import",
        "type": "object",
        "required": ["transactions"],
        "additionalProperties": False,
        # Lets a tool check that a credit doesn't land in an expense category
        "x-category-types": {c.name: c.type.value for c in sorted(importable, key=lambda c: c.name.casefold())},
        # Rules learnt in the import preview; the bank converter applies them to lines its own rules miss
        "x-rules": [{"contains": r.text, "category": r.category.name} for r in import_rules.load(db)],
        "properties": {
            "transactions": {
                "type": "array",
                "maxItems": MAX_ROWS,
                "items": {
                    "type": "object",
                    "required": ["date", "account", "category", "amount"],
                    "additionalProperties": False,
                    "properties": properties,
                },
            }
        },
    }


@router.get("/import/template.csv")
def import_template(_: models.User = Depends(auth.get_current_user_from_token)):
    return Response(
        TEMPLATE,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="budget-import-template.csv"'},
    )
