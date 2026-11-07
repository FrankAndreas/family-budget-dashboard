"""Investments: list, add, change, archive, delete. Parents only."""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import assets, auth, database, models, ownership, schemas
from .money import cents

router = APIRouter()


@router.get("/assets", response_model=List[schemas.Asset])
def list_assets(current_user: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)):
    visible = [a for a in db.query(models.Asset) if ownership.visible_owner(db, current_user, a.owner_id, a.split_id)]
    return sorted((assets.asset_out(db, a) for a in visible), key=lambda a: a["replacement_due"])


@router.get("/assets/{asset_id}", response_model=schemas.AssetDetail)
def read_asset(
    asset_id: str, current_user: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)
):
    asset = assets.get_asset(db, current_user, asset_id)
    expenses = (
        db.query(models.Transaction)
        .filter(models.Transaction.asset_id == asset.id, models.Transaction.asset_purchase.is_(False))
        .order_by(models.Transaction.date.desc())
        .all()
    )
    return {**assets.asset_out(db, asset), "expenses": expenses}


@router.post("/assets", response_model=schemas.Asset)
def create_asset(
    asset: schemas.AssetIn,
    current_user: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    ownership.check_owner(db, current_user, asset.owner_id, asset.split_id)
    tags = ownership.check_tags(db, asset.tag_ids)
    assets.check_lease(asset)
    data = asset.model_dump(exclude={"tag_ids"})
    data["price"] = cents(data["price"])
    db_asset = models.Asset(**data, tags=tags)
    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)
    return assets.asset_out(db, db_asset)


@router.put("/assets/{asset_id}", response_model=schemas.Asset)
def update_asset(
    asset_id: str,
    asset: schemas.AssetIn,
    current_user: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    db_asset = assets.get_asset(db, current_user, asset_id, write=True)
    ownership.check_owner(db, current_user, asset.owner_id, asset.split_id)
    tags = ownership.check_tags(db, asset.tag_ids)
    assets.check_lease(asset)
    for key, value in asset.model_dump(exclude={"tag_ids"}).items():
        setattr(db_asset, key, cents(value) if key == "price" else value)
    db_asset.tags = tags
    db.commit()
    db.refresh(db_asset)
    return assets.asset_out(db, db_asset)


@router.post("/assets/{asset_id}/archive", response_model=schemas.Asset)
def archive_asset(
    asset_id: str,
    body: schemas.AssetArchive,
    current_user: models.User = Depends(auth.require_parent),
    db: Session = Depends(database.get_db),
):
    db_asset = assets.get_asset(db, current_user, asset_id, write=True)
    assets.archive(db_asset, body.archived_on)
    db.commit()
    return assets.asset_out(db, db_asset)


@router.delete("/assets/{asset_id}/archive", response_model=schemas.Asset)
def restore_asset(
    asset_id: str, current_user: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)
):
    db_asset = assets.get_asset(db, current_user, asset_id, write=True)
    db_asset.archived_on = None
    db.commit()
    return assets.asset_out(db, db_asset)


@router.delete("/assets/{asset_id}")
def delete_asset(
    asset_id: str, current_user: models.User = Depends(auth.require_parent), db: Session = Depends(database.get_db)
):
    ownership.unlink_and_delete_asset(db, assets.get_asset(db, current_user, asset_id, write=True))
    db.commit()
    return {"deleted": asset_id}
