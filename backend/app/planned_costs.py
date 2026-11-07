"""Planned costs (yearly bills and monthly common costs): their monthly amount, next due date and shares."""

from sqlalchemy.orm import Session

from . import finance, messages, models, ownership, schemas
from .reports import today

PLANNED_COST_FIELDS = ("id", "name", "category_id", "amount", "due_month", "owner_id", "split_id", "notes")


def planned_cost_out(db: Session, cost: models.PlannedCost) -> dict:
    monthly = finance.monthly_equivalent(cost.amount, cost.frequency.value)
    due = finance.next_due(cost.due_month, today()) if cost.due_month else None
    return {
        **{field: getattr(cost, field) for field in PLANNED_COST_FIELDS},
        "frequency": cost.frequency.value,
        "monthly": monthly,
        "next_due": due,
        "due_soon": bool(due and finance.is_due_soon(due, today())),
        "shares": ownership.monthly_shares(db, monthly, cost.owner_id, cost.split_id),
    }


def validate_planned_cost(db: Session, current_user: models.User, cost: schemas.PlannedCostIn) -> None:
    ownership.check_owner(db, current_user, cost.owner_id, cost.split_id)
    if cost.frequency == "YEARLY" and not cost.due_month:
        raise messages.api_error(400, "bill_due_month")
    if cost.frequency == "MONTHLY" and not cost.split_id:
        raise messages.api_error(400, "monthly_costs_need_split")
    if not db.query(models.Category).filter(models.Category.id == cost.category_id).first():
        raise messages.api_error(400, "category_not_found")


def get_planned_cost(db: Session, current_user: models.User, cost_id: str, write: bool = False) -> models.PlannedCost:
    cost = db.query(models.PlannedCost).filter(models.PlannedCost.id == cost_id).first()
    if not cost or not ownership.visible_owner(db, current_user, cost.owner_id, cost.split_id, write):
        raise messages.api_error(404, "planned_cost_not_found")
    return cost
