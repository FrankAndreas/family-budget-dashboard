"""Planned costs: yearly bills and monthly common costs. Parents only."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, database, models, ownership, planned_costs, schemas
from .money import cents

router = APIRouter()


@router.get("/planned-costs", response_model=List[schemas.PlannedCost])
def list_planned_costs(
    frequency: Optional[str] = None,
    current_user: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.PlannedCost)
    if frequency:
        query = query.filter(models.PlannedCost.frequency == frequency)
    rows = [
        planned_costs.planned_cost_out(db, c)
        for c in query
        if ownership.visible_owner(db, current_user, c.owner_id, c.split_id)
    ]
    return sorted(rows, key=lambda r: (r["next_due"] or date.max, r["name"]))


@router.post("/planned-costs", response_model=schemas.PlannedCost)
def create_planned_cost(
    cost: schemas.PlannedCostIn,
    current_user: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    planned_costs.validate_planned_cost(db, current_user, cost)
    data = cost.model_dump()
    data["amount"] = cents(data["amount"])
    db_cost = models.PlannedCost(**data)
    db.add(db_cost)
    db.commit()
    db.refresh(db_cost)
    return planned_costs.planned_cost_out(db, db_cost)


@router.put("/planned-costs/{cost_id}", response_model=schemas.PlannedCost)
def update_planned_cost(
    cost_id: str,
    cost: schemas.PlannedCostIn,
    current_user: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    db_cost = planned_costs.get_planned_cost(db, current_user, cost_id, write=True)
    planned_costs.validate_planned_cost(db, current_user, cost)
    for key, value in cost.model_dump().items():
        setattr(db_cost, key, cents(value) if key == "amount" else value)
    db.commit()
    db.refresh(db_cost)
    return planned_costs.planned_cost_out(db, db_cost)


@router.delete("/planned-costs/{cost_id}")
def delete_planned_cost(
    cost_id: str, current_user: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)
):
    db.delete(planned_costs.get_planned_cost(db, current_user, cost_id, write=True))
    db.commit()
    return {"deleted": cost_id}
