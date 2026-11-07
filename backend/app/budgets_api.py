"""Budgets: a limit per category or tag, per month or year."""

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, crud, database, messages, models, privacy, reports, schemas
from .privacy import is_dependent

router = APIRouter()


@router.get("/budgets", response_model=List[schemas.Budget])
def get_budgets(
    user_id: Optional[str] = None,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Without user_id: the caller's own budgets. With user_id: someone else's they may view.
    owner = privacy.check_user_access(db, current_user, user_id) if user_id else current_user
    return [reports.budget_out(db, budget) for budget in crud.get_budgets(db, owner.id)]


@router.post("/budgets", response_model=schemas.Budget)
def create_budget(
    budget: schemas.BudgetCreate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    owner = privacy.check_user_access(db, current_user, budget.user_id, write=True) if budget.user_id else current_user
    if is_dependent(owner):
        raise messages.api_error(403, "no_budgets_without_allowance")
    if budget.category_id is not None and not crud.get_category(db, budget.category_id):
        raise messages.api_error(400, "category_not_found")
    if budget.tag_id is not None and not db.query(models.Tag).filter(models.Tag.id == budget.tag_id).first():
        raise messages.api_error(400, "tag_not_found")
    return reports.budget_out(db, crud.create_budget(db, budget=budget, user_id=owner.id))


def get_manageable_budget(db: Session, current_user, budget_id: str):
    db_budget = crud.get_budget(db, budget_id)
    owner = db.query(models.User).filter(models.User.id == db_budget.user_id).first() if db_budget else None
    # Own budgets, or those of someone who shared with EDIT
    if not owner or not privacy.can_write(privacy.access_level(db, current_user, owner)):
        raise messages.api_error(404, "budget_not_found")
    return db_budget


@router.put("/budgets/{budget_id}", response_model=schemas.Budget)
def update_budget(
    budget_id: str,
    budget_update: schemas.BudgetUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return reports.budget_out(
        db, crud.update_budget(db, get_manageable_budget(db, current_user, budget_id), budget_update)
    )


@router.delete("/budgets/{budget_id}", response_model=schemas.Budget)
def delete_budget(
    budget_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    return crud.delete_budget(db, get_manageable_budget(db, current_user, budget_id))
