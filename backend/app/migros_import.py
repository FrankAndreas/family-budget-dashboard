"""Migros receipts from the Cumulus CSV export: one booking per receipt, its articles as lines (spec 2026-10-28).

Each article gets a category and tags from its article rule, else from the AI (first preview only), else Groceries.
Each receipt goes onto the bank booking that paid it (reconcile.payments_for_receipt) or is booked new, so a later
bank import finds it. Like the bank import, the preview and the import are stateless: the frontend sends its choices
back with the file. What was booked is proposed as the articles' rules (spec 2026-10-29); a fallback proposes nothing.
"""

import json
from datetime import timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from . import article_rules, auth, bank_csv, database, items, messages, models, privacy, receipt_ai, reconcile, schemas
from .crud import to_cents
from .migros_csv import Receipt, is_migros, norm, receipts
from .seed import UNSORTED, system_category

router = APIRouter()

MAX_BYTES = 1024 * 1024
SOURCES = ("change", "rule", "ai", "fallback")


def require_parent(user: models.User) -> None:
    if user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_import_migros")


def read_file(file: UploadFile) -> list[Receipt]:
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise messages.api_error(400, "file_too_large")
    text = bank_csv.decode(content)
    if text is None or not is_migros(text):
        raise messages.api_error(400, "migros_file_unknown")
    found = receipts(text)
    if not found:
        raise messages.api_error(400, "file_empty")
    return found


def parse_choices(text: str) -> dict[str, dict]:
    if not text.strip():
        return {"articles": {}, "receipts": {}}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise messages.api_error(400, "migros_choices_invalid")
    if not isinstance(data, dict) or not all(isinstance(data.get(k, {}), dict) for k in ("articles", "receipts")):
        raise messages.api_error(400, "migros_choices_invalid")
    return {"articles": data.get("articles") or {}, "receipts": data.get("receipts") or {}}


def writable_accounts(db: Session, user: models.User) -> list[models.Account]:
    owners = {u.id: u for u in db.query(models.User)}
    return [
        a
        for a in privacy.get_accessible_accounts(db, user)
        if a.user_id in owners and privacy.can_write(privacy.access_level(db, user, owners[a.user_id]))
    ]


def to_utc(receipt: Receipt):
    """The receipt's Swiss time as the naive UTC the database keeps."""
    return receipt.when.replace(tzinfo=reconcile.ZURICH).astimezone(timezone.utc).replace(tzinfo=None)


def fallback_category(db: Session) -> models.Category:
    groceries = db.query(models.Category).filter(models.Category.default_key == "GROCERIES").first()
    return groceries or system_category(db, UNSORTED)


def is_discount(amount: float) -> bool:
    """A Cumulus voucher or a return: it lowers the receipt, takes its main category and proposes no rule."""
    return amount < 0


def articles_of(
    db: Session, user: models.User, found: list[Receipt], chosen: dict[str, dict], ask_ai: bool, skip: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, str], Optional[dict]]:
    """Per article (by norm): category_id, tag_ids and source; the names as first written; and what the AI did. The
    AI isn't asked about articles only on receipts in skip (already imported, or not importable)."""
    names: dict[str, str] = {}
    importable: set[str] = set()
    for receipt in found:
        for line in receipt.lines:
            if not is_discount(line.amount):
                names.setdefault(norm(line.name), line.name)
                if receipt.key not in skip:
                    importable.add(norm(line.name))
    rules = article_rules.load(db)
    categories = {
        c.id: c for c in db.query(models.Category).filter(models.Category.type == models.CategoryType.EXPENSE)
    }
    tag_ids = {t.id for t in db.query(models.Tag)}
    result: dict[str, dict[str, Any]] = {}
    open_names: list[str] = []
    for key, name in names.items():
        choice = chosen.get(key)
        if isinstance(choice, dict) and choice.get("source") in ("change", "ai"):
            if choice.get("category_id") not in categories or not set(choice.get("tag_ids") or []) <= tag_ids:
                raise messages.api_error(400, "migros_choices_invalid")
            if choice["source"] == "change" or key not in rules:
                result[key] = {
                    "category_id": choice["category_id"],
                    "tag_ids": list(dict.fromkeys(choice.get("tag_ids") or [])),
                    "source": choice["source"],
                }
                continue
        if key in rules:
            result[key] = {"category_id": rules[key].category_id, "tag_ids": rules[key].tag_ids, "source": "rule"}
        else:
            open_names.append(name)
    ai = None
    if ask_ai:
        asked = [name for name in open_names if norm(name) in importable]
        suggested, status, message = receipt_ai.suggest_articles(db, user, asked)
        ai = {"status": status, "message": message}
        for name, suggestion in suggested.items():
            result[norm(name)] = {**suggestion, "source": "ai"}
    fallback = fallback_category(db).id
    for name in open_names:
        result.setdefault(norm(name), {"category_id": fallback, "tag_ids": [], "source": "fallback"})
    return result, names, ai


def lines_of(receipt: Receipt, articles: dict[str, dict]) -> list[dict]:
    shown = [
        {"key": norm(line.name), "name": line.name, "amount": line.amount, **articles[norm(line.name)]}
        for line in receipt.lines
        if not is_discount(line.amount)
    ]
    # Discounts take the category with the largest amount on the receipt
    per_category: dict[str, float] = {}
    for line in shown:
        per_category[line["category_id"]] = per_category.get(line["category_id"], 0) + line["amount"]
    main = max(per_category, key=lambda c: per_category[c]) if per_category else None
    discounts: list[dict[str, Any]] = [
        {
            "key": norm(line.name),
            "name": line.name,
            "amount": line.amount,
            "category_id": main,
            "tag_ids": [],
            "source": "discount",
        }
        for line in receipt.lines
        if is_discount(line.amount)
    ]
    return shown + discounts


def payments(db: Session, accounts: list[models.Account], receipt: Receipt) -> list[models.Transaction]:
    """The bank bookings that may have paid the receipt, on any account the importer may book on; the best first."""
    found = []
    for account in accounts:
        found += reconcile.payments_for_receipt(db, account, receipt.when.date(), receipt.total)
    return sorted(found, key=lambda t: fit_of(receipt, t))


def fit_of(receipt: Receipt, payment: models.Transaction) -> tuple[bool, int]:
    """How well a payment fits a receipt: exact amount first, then the nearest day."""
    paid = min(r.booked_on for r in payment.bank_rows)
    return to_cents(-payment.amount) != receipt.total, abs((paid - receipt.when.date()).days)


def maybe_booked(db: Session, accounts: list[models.Account], receipt: Receipt) -> bool:
    """Booked another way already (a photo, a forwarded mail): a Migros receipt on the same day with the same total."""
    start = to_utc(receipt) - timedelta(days=1)
    nearby = db.query(models.Transaction).filter(
        models.Transaction.account_id.in_([a.id for a in accounts]),
        models.Transaction.date >= start,
        models.Transaction.date <= start + timedelta(days=2),
    )
    return any(
        t.items
        and reconcile.swiss_day(t) == receipt.when.date()
        and abs(-t.amount - receipt.total) <= reconcile.TOLERANCE
        and "migros" in (t.description or "").casefold()
        and not (t.reference or "").startswith("migros:")
        for t in nearby
    )


def converter_prefix(receipt: Receipt) -> str:
    """tools/converters/migros.py booked a receipt per category as migros:<ISO day>:<store>:<till>:<number>:..."""
    return f"migros:{receipt.when.date().isoformat()}:{receipt.store}:{receipt.till}:{receipt.number}:"


def already_imported(db: Session, found: list[Receipt]) -> set[str]:
    """The keys of receipts booked before: by this import, or by the converter."""
    references: set[str] = {
        ref
        for (ref,) in db.query(models.Transaction.reference).filter(models.Transaction.reference.like("migros:%"))
        if ref
    }
    return {
        r.key for r in found if r.key in references or any(ref.startswith(converter_prefix(r)) for ref in references)
    }


def assign(
    open_rows: list[tuple[Receipt, dict, list[models.Transaction]]], chosen: dict[str, str]
) -> dict[str, models.Transaction]:
    """Which payment each ticked receipt goes onto. A payment the person chose wins; the others get the free payments,
    the best fits across the whole file first, so a near amount never takes another receipt's exact one."""
    taken: dict[str, models.Transaction] = {}
    claimed: set[str] = set()
    for receipt, row, candidates in open_rows:
        wanted = chosen.get(receipt.key)
        if not row["include"] or not wanted or wanted == "new":
            continue
        payment = next((t for t in candidates if t.id == wanted), None)
        if payment is None or wanted in claimed:
            raise messages.api_error(400, "migros_payment_taken")
        taken[receipt.key] = payment
        claimed.add(wanted)
    pairs = [
        (fit_of(receipt, t), position, receipt.key, t)
        for position, (receipt, row, candidates) in enumerate(open_rows)
        if row["include"] and receipt.key not in chosen
        for t in candidates
    ]
    for _, _, key, payment in sorted(pairs, key=lambda pair: pair[:2]):
        if key not in taken and payment.id not in claimed:
            taken[key] = payment
            claimed.add(payment.id)
    return taken


def checked(
    db: Session, user: models.User, found: list[Receipt], choices: dict[str, dict], ask_ai: bool = False
) -> dict[str, Any]:
    """The preview: the receipts with their lines, payment, account and state; the articles; what the AI did. The
    receipt choices are only what the person changed (include, payment, account), so the rest can follow them."""
    imported = already_imported(db, found)
    skip = imported | {r.key for r in found if r.total <= 0}
    articles, names, ai = articles_of(db, user, found, choices["articles"], ask_ai, skip)
    accounts = writable_accounts(db, user)
    rows = []
    open_rows = []
    for receipt in found:
        choice = choices["receipts"].get(receipt.key) or {}
        row: dict[str, Any] = {
            "key": receipt.key,
            "date": receipt.when.date().isoformat(),
            "time": receipt.when.strftime("%H:%M:%S"),
            "store": receipt.store,
            "total": receipt.total,
            "lines": lines_of(receipt, articles),
            "payments": [],
            "payment": "new",
            "account_id": None,
            "error": None,
        }
        rows.append(row)
        if receipt.total <= 0:
            row.update(status="error", error=messages.text("items_sum_positive"), include=False)
            continue
        if receipt.key in imported:
            row.update(status="imported", include=False)
            continue
        status = "maybe_booked" if maybe_booked(db, accounts, receipt) else "new"
        include = choice.get("include")
        row.update(status=status, include=bool(include) if include is not None else status == "new")
        candidates = payments(db, accounts, receipt)
        row["payments"] = [
            {"id": t.id, "description": t.description, "date": reconcile.swiss_day(t).isoformat(), "amount": t.amount}
            for t in candidates
        ]
        open_rows.append((receipt, row, candidates))
    chosen = {key: c["payment"] for key, c in choices["receipts"].items() if isinstance(c, dict) and c.get("payment")}
    taken = assign(open_rows, chosen)
    # A receipt booked new goes where the newest matched one went (receipts are newest first), else to the person's
    # first own bank account
    matched = [taken[receipt.key].account_id for receipt, _, _ in open_rows if receipt.key in taken]
    own_bank = [a.id for a in accounts if a.user_id == user.id and a.type == models.AccountType.BANK]
    fallbacks = matched or own_bank or [a.id for a in accounts]
    default: Optional[str] = fallbacks[0] if fallbacks else None
    for receipt, row, _ in open_rows:
        choice = choices["receipts"].get(receipt.key) or {}
        row["payment"] = taken[receipt.key].id if receipt.key in taken else "new"
        row["account_id"] = choice.get("account_id") or default
    used = {line["key"] for row in rows if row["include"] for line in row["lines"] if line["source"] != "discount"}
    return {
        "receipts": rows,
        "articles": articles,
        "names": names,
        "accounts": [{"id": a.id, "name": a.name} for a in accounts],
        "new_suggestions": sum(1 for key in used if articles[key]["source"] in ("change", "ai")),
        "ai": ai,
    }


@router.post("/import/migros/preview")
def preview_migros(
    file: UploadFile = File(...),
    choices: str = Form(""),
    ai: str = Form(""),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    result = checked(db, current_user, read_file(file), parse_choices(choices), ai == "1")
    result.pop("names")
    return result


@router.post("/import/migros")
def run_migros(
    file: UploadFile = File(...),
    choices: str = Form(""),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    found = {r.key: r for r in read_file(file)}
    result = checked(db, current_user, list(found.values()), parse_choices(choices))
    onto = booked = 0
    try:
        for row in result["receipts"]:
            if not row["include"] or row["status"] not in ("new", "maybe_booked"):
                continue
            receipt = found[row["key"]]
            lines = [
                schemas.ItemIn(
                    name=line["name"], amount=line["amount"], category_id=line["category_id"], tag_ids=line["tag_ids"]
                )
                for line in row["lines"]
            ]
            if row["payment"] != "new":
                booking: Optional[models.Transaction] = db.get(models.Transaction, row["payment"])
                if booking is None:
                    raise messages.api_error(404, "transaction_not_found")
                onto += 1
            else:
                account = privacy.check_account_access(db, current_user, row["account_id"] or "", write=True)
                booking = models.Transaction(account_id=account.id)
                db.add(booking)
                booked += 1
            booking.description = f"Migros {receipt.store}"
            booking.date = to_utc(receipt)
            booking.reference = receipt.key
            # The export is the receipt a payment rule asked for
            booking.receipt_expected = False
            items.apply(db, current_user, booking, lines)
            db.flush()
            db.refresh(booking)
            reconcile.fit(db, booking)
        # What was booked is proposed as the articles' rules (a parent adds them in Settings), saved with the bookings
        # so a failed import proposes nothing; a fallback proposes nothing, so the AI gets another try
        used = {
            line["key"]
            for row in result["receipts"]
            if row["include"] and row["status"] in ("new", "maybe_booked")
            for line in row["lines"]
            if line["source"] != "discount"
        }
        proposed = [
            (result["names"][key], result["articles"][key]["category_id"], result["articles"][key]["tag_ids"])
            for key in sorted(used)
            if result["articles"][key]["source"] in ("change", "ai")
        ]
        suggested = article_rules.suggest(db, current_user, proposed)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"onto_payments": onto, "booked": booked, "suggestions": suggested}
