"""The common budget's monthly overview, and what a person owns before their data is deleted. Parents only."""

from typing import Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import assets, auth, database, finance, messages, models, ownership, privacy, schemas
from .money import cents

router = APIRouter()


@router.get("/common/overview", response_model=schemas.Overview)
def common_overview(_: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)):
    items: list[dict[str, Any]] = []
    for cost in db.query(models.PlannedCost).filter(models.PlannedCost.split_id.isnot(None)):
        monthly = finance.monthly_equivalent(cost.amount, cost.frequency.value)
        shares = ownership.monthly_shares(db, monthly, None, cost.split_id)
        items.append({"kind": "planned", "id": cost.id, "name": cost.name, "monthly": monthly, "shares": shares})
    items += assets.common_asset_items(db)
    totals: dict[str, float] = {}
    for item in items:
        for user_id, amount in item["shares"].items():
            totals[user_id] = cents(totals.get(user_id, 0.0) + amount)
    return {"items": items, "totals": totals}


@router.get("/users/{user_id}/items", response_model=List[schemas.OwnedItem])
def list_owned_items(
    user_id: str, current_user: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)
):
    """What a person owns, for deciding where it goes when their data is deleted (issue #134): of someone removed in
    the family hub (any parent may delete their data), or of someone whose money this parent sees."""
    owner = db.query(models.User).filter(models.User.id == user_id).first()
    if owner is None:
        raise messages.api_error(404, "user_not_found")
    if owner.is_active is not False and privacy.access_level(db, current_user, owner) is None:
        raise messages.api_error(403, "no_access_to_person")
    return ownership.owned_items(db, user_id)
