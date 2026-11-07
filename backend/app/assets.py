"""Investments: what one costs per month and year, its replacement, and who carries it."""

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from . import crud, finance, messages, models, ownership, reports, schemas
from .reports import today

ASSET_FIELDS = (
    "id",
    "name",
    "price",
    "purchase_date",
    "lifespan_years",
    "owner_id",
    "split_id",
    "notes",
    "tag_ids",
    "archived_on",
    "kind",
    "lease_rate",
    "lease_months",
    "lease_final",
)


def check_lease(asset: schemas.AssetIn) -> None:
    """A lease has a rate and a term, shorter than the time the car is kept; a purchase keeps no lease values."""
    if asset.kind == "PURCHASE":
        asset.lease_rate = asset.lease_months = asset.lease_final = None
        return
    if asset.lease_rate is None or not asset.lease_months or asset.lease_months >= asset.lifespan_years * 12:
        raise messages.api_error(400, "lease_incomplete")


def asset_out(db: Session, asset: models.Asset) -> dict:
    linked = db.query(models.Transaction).filter(models.Transaction.asset_id == asset.id).all()
    # The purchase is in the price already
    follow_ups = [t for t in linked if not t.asset_purchase]
    purchase = next((t for t in linked if t.asset_purchase), None)
    # An archived investment is seen as on the day it left: age and cost per year stop there
    stats = finance.asset_stats(
        asset.price,
        asset.purchase_date,
        asset.lifespan_years,
        sum(crud.cost(t.amount) for t in follow_ups),
        asset.archived_on or today(),
        asset.lease,
    )
    if asset.archived_on:
        stats |= {"monthly_set_aside": 0.0, "monthly_rate": 0.0, "monthly_load": 0.0, "is_due": False}
    return {
        **{field: getattr(asset, field) for field in ASSET_FIELDS},
        **stats,
        "shares": (
            {}
            if asset.archived_on
            else ownership.monthly_shares(db, stats["monthly_load"], asset.owner_id, asset.split_id)
        ),
        "purchase": purchase
        and {
            "transaction_id": purchase.id,
            "amount": abs(purchase.amount),
            "date": reports.swiss_day(purchase.date),
            "attachments": purchase.attachments,
        },
    }


def get_asset(db: Session, current_user: models.User, asset_id: str, write: bool = False) -> models.Asset:
    asset = db.query(models.Asset).filter(models.Asset.id == asset_id).first()
    if not asset or not ownership.visible_owner(db, current_user, asset.owner_id, asset.split_id, write):
        raise messages.api_error(404, "investment_not_found")
    return asset


def common_asset_items(db: Session) -> list[dict]:
    rows: list[dict[str, Any]] = []
    for asset in db.query(models.Asset).filter(models.Asset.split_id.isnot(None), models.Asset.archived_on.is_(None)):
        monthly = finance.asset_plan(asset.price, asset.purchase_date, asset.lifespan_years, today(), asset.lease)[
            "monthly_load"
        ]
        shares = ownership.monthly_shares(db, monthly, None, asset.split_id)
        rows.append({"kind": "asset", "id": asset.id, "name": asset.name, "monthly": monthly, "shares": shares})
    return rows


def archive(asset: models.Asset, day: date) -> None:
    """The investment left (sold, scrapped) on that day: not before it was bought, not in the future."""
    if not asset.purchase_date <= day <= today():
        raise messages.api_error(400, "archive_date_invalid")
    asset.archived_on = day
