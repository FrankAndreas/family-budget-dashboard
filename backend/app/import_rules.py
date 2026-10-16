"""Import rules: text in a row's description → category. Learnt in the import preview ("remember"), applied to rows
that arrive in a fallback category, and handed to the bank converter through the JSON Schema (x-rules)."""

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, database, models, messages
from .seed import OTHER_INCOME, SETTLE_UP, UNSORTED

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
    row = {**raw, "category": category.name}
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
        description = key(raw["description"])
        for rule in rules:
            if key(rule.text) in description and fits(rule.category, kind):
                return with_category(raw, rule.category, kind), None, rule.text
    return raw, None, None


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
        "category": rule.category.name,
        "category_type": rule.category.type.value,
        "toml": toml_block(rule.text, rule.category),
    }


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
    rule = db.query(models.ImportRule).filter(models.ImportRule.id == rule_id).first()
    if not rule:
        raise messages.api_error(404, "rule_not_found")
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}
