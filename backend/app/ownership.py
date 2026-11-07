"""Who an item belongs to (a person, or all parents through a split), who may see and change it, and where it goes
when its owner's data is deleted. Used for investments, yearly bills and planned costs."""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import finance, messages, models, privacy, schemas


def get_split(db: Session, split_id: str) -> models.Split:
    split = db.query(models.Split).filter(models.Split.id == split_id).first()
    if not split:
        raise messages.api_error(400, "split_not_found")
    return split


def visible_owner(
    db: Session, current_user: models.User, owner_id: Optional[str], split_id: Optional[str], write: bool = False
) -> bool:
    """Common items belong to all parents; a personal item follows the access rules for its owner's money."""
    if split_id:
        return True
    owner = db.query(models.User).filter(models.User.id == owner_id).first()
    level = privacy.access_level(db, current_user, owner) if owner else None
    return privacy.can_write(level) if write else level is not None


def check_owner(db: Session, current_user: models.User, owner_id: Optional[str], split_id: Optional[str]) -> None:
    if bool(owner_id) == bool(split_id):
        raise messages.api_error(400, "owner_or_split")
    if split_id:
        get_split(db, split_id)
    elif not visible_owner(db, current_user, owner_id, None, write=True):
        raise messages.api_error(403, "cant_manage_items")


def check_tags(db: Session, tag_ids: list[str]) -> list[models.Tag]:
    wanted = set(tag_ids)
    tags = db.query(models.Tag).filter(models.Tag.id.in_(wanted)).all()
    if len(tags) != len(wanted):
        raise messages.api_error(400, "tag_not_found")
    return tags


def monthly_shares(db: Session, monthly: float, owner_id: Optional[str], split_id: Optional[str]) -> dict[str, float]:
    if split_id:
        split = db.query(models.Split).filter(models.Split.id == split_id).first()
        return finance.split_amount(monthly, split.shares if split else {})
    return {owner_id: monthly} if owner_id else {}


def unlink_and_delete_asset(db: Session, asset: models.Asset) -> None:
    # The follow-up expenses stay as normal expenses
    db.query(models.Transaction).filter(models.Transaction.asset_id == asset.id).update(
        {models.Transaction.asset_id: None}, synchronize_session=False
    )
    db.delete(asset)


# Removing a family member: their investments and yearly bills need a new home first
def owned_items(db: Session, user_id: str) -> list[dict]:
    owned_assets = db.query(models.Asset).filter(models.Asset.owner_id == user_id)
    costs = db.query(models.PlannedCost).filter(models.PlannedCost.owner_id == user_id)
    return [{"kind": "asset", "id": a.id, "name": a.name} for a in owned_assets] + [
        {"kind": "planned", "id": c.id, "name": c.name} for c in costs
    ]


def find_item(db: Session, kind: str, item_id: str) -> models.Asset | models.PlannedCost:
    if kind == "asset":
        return db.query(models.Asset).filter(models.Asset.id == item_id).one()
    return db.query(models.PlannedCost).filter(models.PlannedCost.id == item_id).one()


def apply_item_decisions(db: Session, user_id: str, decisions: list[schemas.ItemDecision]) -> None:
    """Move or delete every item the member owns, as decided. Raises 409/400 before changing anything."""
    owned = {(item["kind"], item["id"]) for item in owned_items(db, user_id)}
    decided = {(d.kind, d.id): d.to for d in decisions if (d.kind, d.id) in owned}
    undecided = [item for item in owned_items(db, user_id) if (item["kind"], item["id"]) not in decided]
    if undecided:
        raise HTTPException(status_code=409, detail={"message": messages.text("decide_items"), "items": undecided})
    # Only yearly bills and investments have an owner (monthly planned costs are always common)
    for target in decided.values():
        kind, _, target_id = target.partition(":")
        valid = (
            target == "delete"
            or (kind == "split" and db.query(models.Split).filter(models.Split.id == target_id).first())
            or (
                kind == "owner"
                and target_id != user_id
                and db.query(models.User).filter(models.User.id == target_id).first()
            )
        )
        if not valid:
            raise messages.api_error(400, "cant_move_item", target=target)
    for (kind, item_id), target in decided.items():
        item = find_item(db, kind, item_id)
        if target == "delete":
            if isinstance(item, models.Asset):
                unlink_and_delete_asset(db, item)
            else:
                db.delete(item)
            continue
        target_kind, _, target_id = target.partition(":")
        item.owner_id, item.split_id = (target_id, None) if target_kind == "owner" else (None, target_id)
