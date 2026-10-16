"""Categories: everyone reads them, parents add, rename, retype and delete them (Settings → Categories).

The categories the code needs (system_key set) are locked: only their icon can change.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, database, i18n, messages, models, schemas

router = APIRouter()

# What can use a category; the "Used by ..." message words are messages "used_<field>_one/_other"
USERS = (
    ("transactions", models.Transaction),
    ("budgets", models.Budget),
    ("planned_costs", models.PlannedCost),
    ("import_rules", models.ImportRule),
)


def require_parent(user: models.User) -> None:
    if user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_categories")


def usage_counts(db: Session) -> dict[str, dict[str, int]]:
    """Per category in use: how many transactions, budgets, planned costs and import rules use it."""
    usage: dict[str, dict[str, int]] = {}
    for field, model in USERS:
        for category_id, count in db.query(model.category_id, func.count()).group_by(model.category_id):
            if category_id:
                usage.setdefault(category_id, {f: 0 for f, _ in USERS})[field] = count
    return usage


def describe(counts: dict[str, int]) -> str:
    """ "Used by 2 transactions and 1 budget" from the non-zero counts."""
    parts = [messages.plural(f"used_{field}", counts[field]) for field, _ in USERS if counts.get(field)]
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + messages.text("list_and") + parts[-1]
    return messages.text("used_by", list=listed)


def name_taken(db: Session, name: str, except_id: Optional[str] = None) -> bool:
    # A 🔒 category's name is taken in every language
    taken = name.casefold()
    return any(
        taken in {n.casefold() for n in i18n.all_names(c) if n} and c.id != except_id for c in db.query(models.Category)
    )


def get_category(db: Session, category_id: str) -> models.Category:
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise messages.api_error(404, "category_not_found")
    return category


def check_kind(kind: Optional[models.CategoryType]) -> None:
    if kind == models.CategoryType.TRANSFER:
        raise messages.api_error(400, "category_income_or_expense")


@router.get("/categories", response_model=List[schemas.Category])
def list_categories(
    db: Session = Depends(database.get_db),
    # Not required, but a logged-in person gets the 🔒 names in their own language
    _user: Optional[models.User] = Depends(auth.get_optional_user),
):
    return db.query(models.Category).all()


@router.get("/categories/usage")
def category_usage(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
) -> dict[str, dict[str, int]]:
    require_parent(current_user)
    return usage_counts(db)


@router.post("/categories", response_model=schemas.Category)
def create_category(
    category: schemas.CategoryCreate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    check_kind(category.type)
    if name_taken(db, category.name):
        raise messages.api_error(400, "category_name_taken")
    db_category = models.Category(name=category.name, type=category.type, icon=category.icon or None, is_global=True)
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


@router.put("/categories/{category_id}", response_model=schemas.Category)
def update_category(
    category_id: str,
    update: schemas.CategoryUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    category = get_category(db, category_id)
    changes = update.model_dump(exclude_unset=True)
    renamed = "name" in changes and changes["name"] != category.name
    retyped = "type" in changes and changes["type"] != category.type
    if category.system_key and (renamed or retyped):
        raise messages.api_error(400, "category_locked")
    if renamed and name_taken(db, changes["name"], category.id):
        raise messages.api_error(400, "category_name_taken")
    if retyped:
        check_kind(changes["type"])
        # Existing bookings got their sign from the type, so it can only change while nothing uses the category
        counts = usage_counts(db).get(category.id)
        if counts:
            raise messages.api_error(400, "category_type_in_use", used=describe(counts))
    for key, value in changes.items():
        setattr(category, key, value or None if key == "icon" else value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    category = get_category(db, category_id)
    if category.system_key:
        raise messages.api_error(400, "category_locked")
    counts = usage_counts(db).get(category.id)
    if counts:
        raise HTTPException(status_code=409, detail=describe(counts))
    db.delete(category)
    db.commit()
    return {"deleted": category_id}
