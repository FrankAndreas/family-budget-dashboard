"""Article rules (Migros import): a receipt article's whole name, ignoring case → category and tags.

An import looks an article up here first, then asks the AI; what it booked becomes the article's rule, so the next
file knows the article without the AI. Parents see and change the rules in Settings.
"""

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


def learn(db: Session, name: str, category: models.Category, tags: list[models.Tag]) -> None:
    """The article's rule becomes this category and these tags (made if new). The caller commits."""
    rule = load(db).get(norm(name))
    if rule is None:
        rule = models.ArticleRule(name=name.strip())
        db.add(rule)
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
    rule = models.ArticleRule(name=name, category_id=category.id, tags=tags)
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
