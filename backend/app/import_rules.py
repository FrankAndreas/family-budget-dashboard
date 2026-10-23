"""Import rules: text in a row's description → category. Learnt in the import preview ("remember"), applied to rows
that arrive in a fallback category, and handed to the bank converter through the JSON Schema (x-rules)."""

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import auth, database, i18n, models, messages
from .seed import OTHER_INCOME, SETTLE_UP, TRANSFER as TRANSFER_KEY, UNSORTED

router = APIRouter()

# The categories the bank converter uses for lines none of its rules recognise
FALLBACKS = (UNSORTED, OTHER_INCOME)
MIN_TEXT, MAX_TEXT = 2, 120
TRANSFER = models.CategoryType.TRANSFER


def key(name: str) -> str:
    return (name or "").strip().casefold()


def require_parent(user: models.User) -> None:
    if user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_import_rules")


def parse_changes(text: str) -> dict[int, dict]:
    """{line: {"category": name, "remember": text}} from the form field (JSON with line numbers as keys)."""
    if not text:
        return {}
    try:
        raw = json.loads(text)
        changes = {int(line): change for line, change in raw.items()}
        if not all(isinstance(c, dict) and isinstance(c.get("category"), str) for c in changes.values()):
            raise ValueError
    except ValueError, AttributeError, TypeError:
        raise messages.api_error(400, "changes_not_json")
    return changes


def load(db: Session) -> list[models.ImportRule]:
    return db.query(models.ImportRule).order_by(models.ImportRule.created_at, models.ImportRule.id).all()


def fits(category: models.Category, kind) -> bool:
    return category.type == kind or category.type == TRANSFER


def with_category(raw: dict, category: models.Category, kind) -> dict:
    row = {**raw, "category": i18n.category_name(category)}
    if category.type == TRANSFER:
        # The sign stays: an expense row is money out, an income row money in
        row["direction"] = "out" if kind == models.CategoryType.EXPENSE else "in"
    return row


def adjust(raw: dict, change: Optional[dict], lookups, rules: list) -> tuple[dict, Optional[str], Optional[str]]:
    """The row with the user's change or a matching rule applied; plus a problem and the rule's text."""
    file_category = lookups.categories.get(key(raw["category"]))
    kind = file_category.type if file_category else None
    if change:
        target = lookups.categories.get(key(change["category"]))
        allowed = (
            kind in (models.CategoryType.INCOME, models.CategoryType.EXPENSE)
            and target is not None
            and target.system_key != SETTLE_UP
            and fits(target, kind)
        )
        if not allowed:
            return raw, f"Can't change {raw['category']} to {change['category']}", None
        return with_category(raw, target, kind), None, None
    if file_category and file_category.system_key in FALLBACKS:
        rule = find(rules, raw["description"], kind)
        if rule:
            return with_category(raw, rule.category, kind), None, rule.text
    return raw, None, None


def pattern(text: str) -> re.Pattern:
    """The text as whole words: no letter or digit directly before or after it, ignoring case."""
    return re.compile(r"(?<![^\W_])" + re.escape(text.strip()) + r"(?![^\W_])", re.IGNORECASE)


def find(rules: list[models.ImportRule], description: str, kind) -> Optional[models.ImportRule]:
    """The rule for a description: the longest matching text whose category fits; equal length → the older one."""
    # sorted() keeps the order of equal lengths, and load() returns the oldest first
    for rule in sorted(rules, key=lambda r: -len(r.text.strip())):
        if fits(rule.category, kind) and pattern(rule.text).search(description or ""):
            return rule
    return None


def remember_problem(text: str) -> Optional[str]:
    return None if MIN_TEXT <= len(text.strip()) <= MAX_TEXT else f"rule text: {MIN_TEXT} to {MAX_TEXT} characters"


def remember(db: Session, text: str, category: models.Category) -> None:
    """Save text → category; the same text (ignoring case) updates the existing rule. The caller commits."""
    text = text.strip()
    existing = next((r for r in load(db) if key(r.text) == key(text)), None)
    if existing:
        existing.category_id = category.id
    else:
        db.add(models.ImportRule(text=text, category_id=category.id))
    db.flush()


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def toml_block(text: str, category: models.Category) -> str:
    """The rule for converter.toml: the text as a regular expression (bank.py matches ignoring case)."""
    target = 'action = "transfer"' if category.type == TRANSFER else f"category = {toml_string(category.name)}"
    return f"[[bank.rules]]\nmatch = {toml_string(re.escape(text))}\n{target}\n"


def rule_out(rule: models.ImportRule) -> dict:
    return {
        "id": rule.id,
        "text": rule.text,
        "category": i18n.category_name(rule.category),
        "category_type": rule.category.type.value,
        "category_id": rule.category_id,
        "receipt_expected": bool(rule.receipt_expected),
        "toml": toml_block(rule.text, rule.category),
    }


class RuleIn(BaseModel):
    text: str
    category_id: str
    receipt_expected: bool = False


class RuleUpdate(BaseModel):
    text: Optional[str] = None
    category_id: Optional[str] = None
    receipt_expected: Optional[bool] = None


def checked_text(db: Session, text: str, rule_id: Optional[str] = None) -> str:
    problem = remember_problem(text)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if any(key(r.text) == key(text) and r.id != rule_id for r in load(db)):
        raise messages.api_error(400, "rule_exists")
    return text.strip()


def checked_category(db: Session, category_id: str) -> models.Category:
    """Income, expense or the Transfer category; Settle up and the like are booked by the app itself."""
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise messages.api_error(404, "category_not_found")
    plain = category.type in (models.CategoryType.INCOME, models.CategoryType.EXPENSE)
    if not plain and category.system_key != TRANSFER_KEY:
        raise messages.api_error(400, "rule_category_invalid")
    return category


def get_rule(db: Session, rule_id: str) -> models.ImportRule:
    rule = db.query(models.ImportRule).filter(models.ImportRule.id == rule_id).first()
    if not rule:
        raise messages.api_error(404, "rule_not_found")
    return rule


@router.post("/import/rules")
def create_rule(
    rule_in: RuleIn,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    rule = models.ImportRule(
        text=checked_text(db, rule_in.text),
        category_id=checked_category(db, rule_in.category_id).id,
        receipt_expected=rule_in.receipt_expected,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule_out(rule)


@router.put("/import/rules/{rule_id}")
def update_rule(
    rule_id: str,
    update: RuleUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    rule = get_rule(db, rule_id)
    if update.text is not None:
        rule.text = checked_text(db, update.text, rule.id)
    if update.category_id is not None:
        rule.category_id = checked_category(db, update.category_id).id
    if update.receipt_expected is not None:
        rule.receipt_expected = update.receipt_expected
    db.commit()
    db.refresh(rule)
    return rule_out(rule)


@router.get("/import/rules")
def list_rules(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    require_parent(current_user)
    return [rule_out(r) for r in load(db)]


@router.delete("/import/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    rule = get_rule(db, rule_id)
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}
