"""Common budget, splits, settlements, planned costs (yearly bills) and assets (investments). Parents only."""

from datetime import date, datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, crud, database, finance, models, privacy, reports, schemas, messages
from .seed import SETTLE_UP, system_category

router = APIRouter()

MAX_SPLITS = 4


def require_parent(current_user: models.User = Depends(auth.get_current_user_from_token)) -> models.User:
    if current_user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "common_parents_only")
    return current_user


def get_split(db: Session, split_id: str) -> models.Split:
    split = db.query(models.Split).filter(models.Split.id == split_id).first()
    if not split:
        raise messages.api_error(400, "split_not_found")
    return split


def validate_split(db: Session, split: schemas.SplitIn, split_id: Optional[str] = None) -> None:
    parent_ids = {p.id for p in privacy.active_parents(db)}
    if set(split.shares) != parent_ids:
        raise messages.api_error(400, "split_every_parent")
    if sum(split.shares.values()) != 100:
        raise messages.api_error(400, "split_sum_100")
    same_name = db.query(models.Split).filter(models.Split.name == split.name, models.Split.id != split_id).first()
    if same_name:
        raise messages.api_error(400, "split_name_taken")


@router.get("/splits", response_model=List[schemas.Split])
def list_splits(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    return db.query(models.Split).order_by(models.Split.name).all()


@router.post("/splits", response_model=schemas.Split)
def create_split(
    split: schemas.SplitIn, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    if db.query(models.Split).count() >= MAX_SPLITS:
        raise messages.api_error(400, "max_splits", count=MAX_SPLITS)
    validate_split(db, split)
    db_split = models.Split(name=split.name, shares=split.shares)
    db.add(db_split)
    db.commit()
    db.refresh(db_split)
    return db_split


@router.put("/splits/{split_id}", response_model=schemas.Split)
def update_split(
    split_id: str,
    split: schemas.SplitIn,
    _: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    db_split = get_split(db, split_id)
    validate_split(db, split, split_id)
    db_split.name, db_split.shares = split.name, split.shares
    db.commit()
    db.refresh(db_split)
    return db_split


@router.delete("/splits/{split_id}", response_model=schemas.Split)
def delete_split(split_id: str, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    db_split = get_split(db, split_id)
    in_use = any(
        db.query(model).filter(model.split_id == split_id).first()
        for model in (models.PlannedCost, models.Asset, models.Wish)
    )
    if in_use:
        raise messages.api_error(409, "split_in_use")
    # Shared expenses keep the percentages they were booked with (split_shares); only the link goes
    db.query(models.Transaction).filter(models.Transaction.split_id == split_id).update(
        {models.Transaction.split_id: None}, synchronize_session=False
    )
    db.delete(db_split)
    db.commit()
    return db_split


def shared_transactions(db: Session) -> list[tuple[models.Transaction, str]]:
    """Every shared expense with its payer's user id, newest first."""
    rows = (
        db.query(models.Transaction, models.Account.user_id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        # Shared = booked with the split's percentages (the split itself may have been deleted since)
        .filter(func.json_type(models.Transaction.split_shares) == "object")
        .order_by(models.Transaction.date.desc())
        .all()
    )
    return [(transaction, payer) for transaction, payer in rows]


def shared_expense_rows(db: Session) -> list[tuple[str, float, dict[str, int]]]:
    return [(payer, abs(t.amount), t.split_shares or {}) for t, payer in shared_transactions(db)]


def settlement_rows(db: Session) -> list[tuple[str, str, float]]:
    return [(s.from_user_id, s.to_user_id, s.amount) for s in db.query(models.Settlement)]


@router.get("/common/balance", response_model=List[schemas.Balance])
def common_balance(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    net = finance.balances(shared_expense_rows(db), settlement_rows(db))
    for parent in privacy.active_parents(db):
        net.setdefault(parent.id, 0.0)
    return [{"user_id": user_id, "amount": amount} for user_id, amount in net.items()]


@router.get("/common/expenses", response_model=List[schemas.SharedExpense])
def common_expenses(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    split_names = {s.id: s.name for s in db.query(models.Split)}
    return [
        {
            "transaction_id": t.id,
            "date": t.date,
            "description": t.description,
            "amount": abs(t.amount),
            "payer_id": payer,
            "split_name": split_names.get(t.split_id or ""),
            "shares": finance.split_amount(abs(t.amount), t.split_shares or {}),
        }
        for t, payer in shared_transactions(db)
    ]


def parent_account(db: Session, account_id: str, user_id: str) -> models.Account:
    account = crud.get_account(db, account_id)
    if not account or account.user_id != user_id:
        raise messages.api_error(400, "settle_pick_accounts")
    return account


@router.get("/settlements", response_model=List[schemas.Settlement])
def list_settlements(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    return db.query(models.Settlement).order_by(models.Settlement.date.desc()).all()


@router.post("/settlements", response_model=schemas.Settlement)
def create_settlement(
    settlement: schemas.SettlementCreate,
    _: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    # Also a deactivated parent, whose open balance must still be settled
    parent_ids = {p.id for p in db.query(models.User.id).filter(models.User.role == models.UserRole.PARENT)}
    between = {settlement.from_user_id, settlement.to_user_id}
    if settlement.from_user_id == settlement.to_user_id or not between <= parent_ids:
        raise messages.api_error(400, "settle_two_parents")
    from_account = parent_account(db, settlement.from_account_id, settlement.from_user_id)
    to_account = parent_account(db, settlement.to_account_id, settlement.to_user_id)
    category = system_category(db, SETTLE_UP)
    amount = crud.to_cents(settlement.amount)
    when = crud.to_naive_utc(settlement.date) if settlement.date else datetime.utcnow()

    paid, received = (
        models.Transaction(
            account_id=account.id, category_id=category.id, amount=sign * amount, date=when, description="Settle up"
        )
        for account, sign in ((from_account, -1), (to_account, 1))
    )
    db.add_all([paid, received])
    db.flush()
    db_settlement = models.Settlement(
        from_user_id=settlement.from_user_id,
        to_user_id=settlement.to_user_id,
        amount=amount,
        date=when,
        from_transaction_id=paid.id,
        to_transaction_id=received.id,
    )
    db.add(db_settlement)
    db.commit()
    db.refresh(db_settlement)
    return db_settlement


@router.delete("/settlements/{settlement_id}", response_model=schemas.Settlement)
def delete_settlement(
    settlement_id: str, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    db_settlement = db.query(models.Settlement).filter(models.Settlement.id == settlement_id).first()
    if not db_settlement:
        raise messages.api_error(404, "settlement_not_found")
    transaction_ids = (db_settlement.from_transaction_id, db_settlement.to_transaction_id)
    # The record points to its two transactions, so it goes first
    db.delete(db_settlement)
    db.flush()
    for transaction_id in transaction_ids:
        transaction = crud.get_transaction(db, transaction_id)
        if transaction:
            crud.delete_transaction(db, transaction)
    db.commit()
    return db_settlement


def today() -> date:
    return date.today()


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


def check_tag(db: Session, tag_id: Optional[str]) -> None:
    if tag_id and not db.query(models.Tag).filter(models.Tag.id == tag_id).first():
        raise messages.api_error(400, "tag_not_found")


def monthly_shares(db: Session, monthly: float, owner_id: Optional[str], split_id: Optional[str]) -> dict[str, float]:
    if split_id:
        split = db.query(models.Split).filter(models.Split.id == split_id).first()
        return finance.split_amount(monthly, split.shares if split else {})
    return {owner_id: monthly} if owner_id else {}


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
        "shares": monthly_shares(db, monthly, cost.owner_id, cost.split_id),
    }


def validate_planned_cost(db: Session, current_user: models.User, cost: schemas.PlannedCostIn) -> None:
    check_owner(db, current_user, cost.owner_id, cost.split_id)
    if cost.frequency == "YEARLY" and not cost.due_month:
        raise messages.api_error(400, "bill_due_month")
    if cost.frequency == "MONTHLY" and not cost.split_id:
        raise messages.api_error(400, "monthly_costs_need_split")
    if not db.query(models.Category).filter(models.Category.id == cost.category_id).first():
        raise messages.api_error(400, "category_not_found")


def get_planned_cost(db: Session, current_user: models.User, cost_id: str, write: bool = False) -> models.PlannedCost:
    cost = db.query(models.PlannedCost).filter(models.PlannedCost.id == cost_id).first()
    if not cost or not visible_owner(db, current_user, cost.owner_id, cost.split_id, write):
        raise messages.api_error(404, "planned_cost_not_found")
    return cost


@router.get("/planned-costs", response_model=List[schemas.PlannedCost])
def list_planned_costs(
    frequency: Optional[str] = None,
    current_user: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.PlannedCost)
    if frequency:
        query = query.filter(models.PlannedCost.frequency == frequency)
    rows = [planned_cost_out(db, c) for c in query if visible_owner(db, current_user, c.owner_id, c.split_id)]
    return sorted(rows, key=lambda r: (r["next_due"] or date.max, r["name"]))


@router.post("/planned-costs", response_model=schemas.PlannedCost)
def create_planned_cost(
    cost: schemas.PlannedCostIn,
    current_user: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    validate_planned_cost(db, current_user, cost)
    data = cost.model_dump()
    data["amount"] = finance.cents(data["amount"])
    db_cost = models.PlannedCost(**data)
    db.add(db_cost)
    db.commit()
    db.refresh(db_cost)
    return planned_cost_out(db, db_cost)


@router.put("/planned-costs/{cost_id}", response_model=schemas.PlannedCost)
def update_planned_cost(
    cost_id: str,
    cost: schemas.PlannedCostIn,
    current_user: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    db_cost = get_planned_cost(db, current_user, cost_id, write=True)
    validate_planned_cost(db, current_user, cost)
    for key, value in cost.model_dump().items():
        setattr(db_cost, key, finance.cents(value) if key == "amount" else value)
    db.commit()
    db.refresh(db_cost)
    return planned_cost_out(db, db_cost)


@router.delete("/planned-costs/{cost_id}")
def delete_planned_cost(
    cost_id: str, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    db.delete(get_planned_cost(db, current_user, cost_id, write=True))
    db.commit()
    return {"deleted": cost_id}


@router.get("/common/overview", response_model=schemas.Overview)
def common_overview(_: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    items: list[dict[str, Any]] = []
    for cost in db.query(models.PlannedCost).filter(models.PlannedCost.split_id.isnot(None)):
        monthly = finance.monthly_equivalent(cost.amount, cost.frequency.value)
        shares = monthly_shares(db, monthly, None, cost.split_id)
        items.append({"kind": "planned", "id": cost.id, "name": cost.name, "monthly": monthly, "shares": shares})
    items += common_asset_items(db)
    totals: dict[str, float] = {}
    for item in items:
        for user_id, amount in item["shares"].items():
            totals[user_id] = finance.cents(totals.get(user_id, 0.0) + amount)
    return {"items": items, "totals": totals}


ASSET_FIELDS = (
    "id",
    "name",
    "price",
    "purchase_date",
    "lifespan_years",
    "owner_id",
    "split_id",
    "notes",
    "tag_id",
    "archived_on",
)


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
        sum(abs(t.amount) for t in follow_ups),
        asset.archived_on or today(),
    )
    if asset.archived_on:
        stats |= {"monthly_set_aside": 0.0, "is_due": False}
    return {
        **{field: getattr(asset, field) for field in ASSET_FIELDS},
        **stats,
        "shares": (
            {} if asset.archived_on else monthly_shares(db, stats["monthly_set_aside"], asset.owner_id, asset.split_id)
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
    if not asset or not visible_owner(db, current_user, asset.owner_id, asset.split_id, write):
        raise messages.api_error(404, "investment_not_found")
    return asset


def common_asset_items(db: Session) -> list[dict]:
    items: list[dict[str, Any]] = []
    for asset in db.query(models.Asset).filter(models.Asset.split_id.isnot(None), models.Asset.archived_on.is_(None)):
        monthly = finance.cents(asset.price / (asset.lifespan_years * 12))
        shares = monthly_shares(db, monthly, None, asset.split_id)
        items.append({"kind": "asset", "id": asset.id, "name": asset.name, "monthly": monthly, "shares": shares})
    return items


@router.get("/assets", response_model=List[schemas.Asset])
def list_assets(current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    assets = [a for a in db.query(models.Asset) if visible_owner(db, current_user, a.owner_id, a.split_id)]
    return sorted((asset_out(db, a) for a in assets), key=lambda a: a["replacement_due"])


@router.get("/assets/{asset_id}", response_model=schemas.AssetDetail)
def read_asset(
    asset_id: str, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    asset = get_asset(db, current_user, asset_id)
    expenses = (
        db.query(models.Transaction)
        .filter(models.Transaction.asset_id == asset.id, models.Transaction.asset_purchase.is_(False))
        .order_by(models.Transaction.date.desc())
        .all()
    )
    return {**asset_out(db, asset), "expenses": expenses}


@router.post("/assets", response_model=schemas.Asset)
def create_asset(
    asset: schemas.AssetIn, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    check_owner(db, current_user, asset.owner_id, asset.split_id)
    check_tag(db, asset.tag_id)
    data = asset.model_dump()
    data["price"] = finance.cents(data["price"])
    db_asset = models.Asset(**data)
    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)
    return asset_out(db, db_asset)


@router.put("/assets/{asset_id}", response_model=schemas.Asset)
def update_asset(
    asset_id: str,
    asset: schemas.AssetIn,
    current_user: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    db_asset = get_asset(db, current_user, asset_id, write=True)
    check_owner(db, current_user, asset.owner_id, asset.split_id)
    check_tag(db, asset.tag_id)
    for key, value in asset.model_dump().items():
        setattr(db_asset, key, finance.cents(value) if key == "price" else value)
    db.commit()
    db.refresh(db_asset)
    return asset_out(db, db_asset)


@router.post("/assets/{asset_id}/archive", response_model=schemas.Asset)
def archive_asset(
    asset_id: str,
    body: schemas.AssetArchive,
    current_user: models.User = Depends(require_parent),
    db: Session = Depends(database.get_db),
):
    db_asset = get_asset(db, current_user, asset_id, write=True)
    if not db_asset.purchase_date <= body.archived_on <= today():
        raise messages.api_error(400, "archive_date_invalid")
    db_asset.archived_on = body.archived_on
    db.commit()
    return asset_out(db, db_asset)


@router.delete("/assets/{asset_id}/archive", response_model=schemas.Asset)
def restore_asset(
    asset_id: str, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    db_asset = get_asset(db, current_user, asset_id, write=True)
    db_asset.archived_on = None
    db.commit()
    return asset_out(db, db_asset)


def unlink_and_delete_asset(db: Session, asset: models.Asset) -> None:
    # The follow-up expenses stay as normal expenses
    db.query(models.Transaction).filter(models.Transaction.asset_id == asset.id).update(
        {models.Transaction.asset_id: None}, synchronize_session=False
    )
    db.delete(asset)


@router.delete("/assets/{asset_id}")
def delete_asset(
    asset_id: str, current_user: models.User = Depends(require_parent), db: Session = Depends(database.get_db)
):
    unlink_and_delete_asset(db, get_asset(db, current_user, asset_id, write=True))
    db.commit()
    return {"deleted": asset_id}


# Removing a family member: their investments and yearly bills need a new home first
def owned_items(db: Session, user_id: str) -> list[dict]:
    assets = db.query(models.Asset).filter(models.Asset.owner_id == user_id)
    costs = db.query(models.PlannedCost).filter(models.PlannedCost.owner_id == user_id)
    return [{"kind": "asset", "id": a.id, "name": a.name} for a in assets] + [
        {"kind": "planned", "id": c.id, "name": c.name} for c in costs
    ]


def find_item(db: Session, kind: str, item_id: str) -> models.Asset | models.PlannedCost:
    if kind == "asset":
        return db.query(models.Asset).filter(models.Asset.id == item_id).one()
    return db.query(models.PlannedCost).filter(models.PlannedCost.id == item_id).one()


@router.get("/users/{user_id}/items", response_model=List[schemas.OwnedItem])
def list_owned_items(user_id: str, _: models.User = Depends(require_parent), db: Session = Depends(database.get_db)):
    return owned_items(db, user_id)


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
