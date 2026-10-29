"""Article rules (Migros import): a receipt article's whole name, ignoring case → category and tags.

An import looks an article up here first, then asks the AI; what it booked becomes the article's rule, so the next
file knows the article without the AI. Parents see and change the rules in Settings.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from . import auth, database, i18n, messages, models
from .import_rules import require_parent
from .migros_csv import norm

router = APIRouter()


def load(db: Session) -> dict[str, models.ArticleRule]:
    """Every rule by its normalised name."""
    query = db.query(models.ArticleRule).options(selectinload(models.ArticleRule.tags))
    return {norm(rule.name): rule for rule in query}


def learn(
    db: Session,
    name: str,
    category: models.Category,
    tags: list[models.Tag],
    rules: Optional[dict[str, models.ArticleRule]] = None,
) -> None:
    """The article's rule becomes this category and these tags (made if new). rules: load(db), given once for many
    articles (a new rule is added to it). The caller commits."""
    rules = load(db) if rules is None else rules
    rule = rules.get(norm(name))
    if rule is None:
        rule = models.ArticleRule(name=name.strip(), name_key=norm(name))
        db.add(rule)
        rules[norm(name)] = rule
    rule.category_id = category.id
    rule.tags = tags
    db.flush()


def rule_out(rule: models.ArticleRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "category_id": rule.category_id,
        "category": i18n.category_name(rule.category),
        "tag_ids": rule.tag_ids,
    }


class RuleIn(BaseModel):
    name: str
    category_id: str
    tag_ids: list[str] = []


def checked(db: Session, rule_in: RuleIn, rule_id: Optional[str] = None) -> tuple[str, models.Category, list]:
    name = rule_in.name.strip()
    if not name or len(name) > 200:
        raise messages.api_error(400, "article_rule_name_invalid")
    other = load(db).get(norm(name))
    if other and other.id != rule_id:
        raise messages.api_error(400, "article_rule_taken")
    category = db.get(models.Category, rule_in.category_id)
    if not category or category.type != models.CategoryType.EXPENSE:
        raise messages.api_error(400, "items_need_expense_category")
    wanted = set(rule_in.tag_ids)
    tags = db.query(models.Tag).filter(models.Tag.id.in_(wanted)).all()
    if len(tags) != len(wanted):
        raise messages.api_error(400, "tag_not_found")
    return name, category, tags


def get_rule(db: Session, rule_id: str) -> models.ArticleRule:
    rule = db.get(models.ArticleRule, rule_id)
    if not rule:
        raise messages.api_error(404, "article_rule_not_found")
    return rule


@router.get("/article-rules")
def list_rules(
    q: str = "",
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    found = [r for r in load(db).values() if norm(q) in norm(r.name)]
    return [rule_out(r) for r in sorted(found, key=lambda r: norm(r.name))]


@router.post("/article-rules")
def create_rule(
    rule_in: RuleIn,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    name, category, tags = checked(db, rule_in)
    rule = models.ArticleRule(name=name, name_key=norm(name), category_id=category.id, tags=tags)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule_out(rule)


@router.put("/article-rules/{rule_id}")
def update_rule(
    rule_id: str,
    rule_in: RuleIn,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    rule = get_rule(db, rule_id)
    rule.name, category, rule.tags = checked(db, rule_in, rule.id)
    rule.name_key = norm(rule.name)
    rule.category_id = category.id
    db.commit()
    db.refresh(rule)
    return rule_out(rule)


@router.delete("/article-rules/{rule_id}")
def delete_rule(
    rule_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    db.delete(get_rule(db, rule_id))
    db.commit()
    return {"deleted": rule_id}


# Suggestions: what bookings propose; nothing enters the rules without a parent's Add (spec 2026-10-29)


def suggest(db: Session, user: models.User, lines: list[tuple[str, str, list[str]]]) -> int:
    """Propose a rule per booked line (name, category_id, tag_ids): one suggestion per article, the latest booking
    wins; none for a line its rule already gives, nor for a child's booking. How many were made or changed. The caller
    commits."""
    if user.role != models.UserRole.PARENT:
        return 0
    rules = load(db)
    waiting = {s.name_key: s for s in db.query(models.ArticleRuleSuggestion)}
    tags = {t.id: t for t in db.query(models.Tag)}
    changed = 0
    for name, category_id, tag_ids in lines:
        key = norm(name)
        if not key:
            continue
        wanted = sorted(dict.fromkeys(t for t in tag_ids if t in tags))
        rule = rules.get(key)
        if rule and rule.category_id == category_id and sorted(rule.tag_ids) == wanted:
            # Booked as its rule says: nothing new (and an older proposal for it is settled)
            if key in waiting:
                db.delete(waiting.pop(key))
            continue
        suggestion = waiting.get(key)
        if suggestion is None:
            suggestion = models.ArticleRuleSuggestion(name=name.strip(), name_key=key)
            db.add(suggestion)
            waiting[key] = suggestion
        elif suggestion.category_id == category_id and sorted(suggestion.tag_ids) == wanted:
            continue
        suggestion.category_id = category_id
        suggestion.tags = [tags[t] for t in wanted]
        suggestion.updated_at = datetime.utcnow()
        changed += 1
    db.flush()
    return changed


def suggestion_out(suggestion: models.ArticleRuleSuggestion, rules: dict[str, models.ArticleRule]) -> dict:
    rule = rules.get(suggestion.name_key)
    return {
        "id": suggestion.id,
        "name": suggestion.name,
        "category_id": suggestion.category_id,
        "category": i18n.category_name(suggestion.category),
        "tag_ids": suggestion.tag_ids,
        # The rule it would change
        "rule": rule and {"category": i18n.category_name(rule.category), "tag_ids": rule.tag_ids},
    }


class SuggestionAdd(BaseModel):
    category_id: Optional[str] = None
    tag_ids: Optional[list[str]] = None


def get_suggestion(db: Session, suggestion_id: str) -> models.ArticleRuleSuggestion:
    suggestion = db.get(models.ArticleRuleSuggestion, suggestion_id)
    if not suggestion:
        raise messages.api_error(404, "article_suggestion_not_found")
    return suggestion


def adopt(db: Session, suggestion: models.ArticleRuleSuggestion, change: Optional[SuggestionAdd] = None) -> None:
    """The suggestion becomes its article's rule (made or updated), with any change; then it is gone."""
    change = change or SuggestionAdd()
    rule_in = RuleIn(
        name=suggestion.name,
        category_id=change.category_id or suggestion.category_id,
        tag_ids=suggestion.tag_ids if change.tag_ids is None else change.tag_ids,
    )
    existing = load(db).get(suggestion.name_key)
    _, category, tags = checked(db, rule_in, existing.id if existing else None)
    learn(db, existing.name if existing else suggestion.name, category, tags)
    db.delete(suggestion)


@router.get("/article-rules/suggestions")
def list_suggestions(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    require_parent(current_user)
    rules = load(db)
    query = db.query(models.ArticleRuleSuggestion).options(selectinload(models.ArticleRuleSuggestion.tags))
    found = sorted(query, key=lambda s: s.name.casefold())
    return [suggestion_out(s, rules) for s in sorted(found, key=lambda s: s.updated_at or datetime.min, reverse=True)]


@router.post("/article-rules/suggestions/add-all")
def add_all_suggestions(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    require_parent(current_user)
    waiting = db.query(models.ArticleRuleSuggestion).all()
    for suggestion in waiting:
        adopt(db, suggestion)
    db.commit()
    return {"added": len(waiting)}


@router.post("/article-rules/suggestions/{suggestion_id}/add")
def add_suggestion(
    suggestion_id: str,
    change: SuggestionAdd,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    suggestion = get_suggestion(db, suggestion_id)
    key = suggestion.name_key
    adopt(db, suggestion, change)
    db.commit()
    return rule_out(load(db)[key])


@router.delete("/article-rules/suggestions/{suggestion_id}")
def ignore_suggestion(
    suggestion_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    db.delete(get_suggestion(db, suggestion_id))
    db.commit()
    return {"deleted": suggestion_id}
