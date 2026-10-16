"""Wishes: things to buy, in each owner's own order, and the parents' family plan (one ranking, running total).

Who sees and changes a wish follows the rules for its owner's money; common wishes belong to all parents.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, database, finance, models, privacy, schemas
from .common_api import get_split

router = APIRouter()

FIELDS = (
    "id",
    "name",
    "estimate",
    "notes",
    "owner_id",
    "split_id",
    "best_price",
    "best_shop",
    "best_url",
    "best_checked",
    "position",
    "family_position",
    "bought_on",
)


def is_parent(user: models.User) -> bool:
    return user.role == models.UserRole.PARENT


def can_see(db: Session, user: models.User, owner_id: Optional[str], split_id: Optional[str], write=False) -> bool:
    if split_id:
        return is_parent(user)
    owner = db.query(models.User).filter(models.User.id == owner_id).first()
    level = privacy.access_level(db, user, owner) if owner else None
    return privacy.can_write(level) if write else level is not None


def visible_wishes(db: Session, user: models.User) -> list[models.Wish]:
    return [w for w in db.query(models.Wish) if can_see(db, user, w.owner_id, w.split_id)]


def wish_out(db: Session, user: models.User, wish: models.Wish) -> dict:
    price = wish.best_price if wish.best_price is not None else wish.estimate
    return {
        **{field: getattr(wish, field) for field in FIELDS},
        "price": price,
        "can_edit": can_see(db, user, wish.owner_id, wish.split_id, write=True),
        "in_family_plan": wish.family_position is not None,
    }


def get_wish(db: Session, user: models.User, wish_id: str, write: bool = False) -> models.Wish:
    wish = db.query(models.Wish).filter(models.Wish.id == wish_id).first()
    if not wish or not can_see(db, user, wish.owner_id, wish.split_id):
        raise HTTPException(status_code=404, detail="Wish not found")
    if write and not can_see(db, user, wish.owner_id, wish.split_id, write=True):
        raise HTTPException(status_code=403, detail="You can't change this wish")
    return wish


def check_owner(db: Session, user: models.User, wish: schemas.WishIn) -> None:
    if bool(wish.owner_id) == bool(wish.split_id):
        raise HTTPException(status_code=400, detail="Choose either an owner or a split")
    if wish.split_id:
        if not is_parent(user):
            raise HTTPException(status_code=403, detail="Only parents can add common wishes")
        get_split(db, wish.split_id)
    elif not can_see(db, user, wish.owner_id, None, write=True):
        raise HTTPException(status_code=403, detail="You can't manage that person's wishes")


def same_owner(owner_id: Optional[str], split_id: Optional[str]):
    return models.Wish.split_id == split_id if split_id else models.Wish.owner_id == owner_id


def next_position(db: Session, column, *filters) -> int:
    return (db.query(func.max(column)).filter(*filters).scalar() or 0) + 1


@router.get("/wishes", response_model=List[schemas.Wish])
def list_wishes(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    wishes = sorted(visible_wishes(db, current_user), key=lambda w: (w.split_id or "", w.owner_id or "", w.position))
    return [wish_out(db, current_user, w) for w in wishes]


@router.post("/wishes", response_model=schemas.Wish)
def create_wish(
    wish: schemas.WishIn,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    check_owner(db, current_user, wish)
    db_wish = models.Wish(**wish.model_dump())
    db_wish.position = next_position(db, models.Wish.position, same_owner(wish.owner_id, wish.split_id))
    if wish.split_id:
        # Common wishes are always in the family plan
        db_wish.family_position = next_position(db, models.Wish.family_position)
    db.add(db_wish)
    db.commit()
    db.refresh(db_wish)
    return wish_out(db, current_user, db_wish)


@router.put("/wishes/{wish_id}", response_model=schemas.Wish)
def update_wish(
    wish_id: str,
    wish: schemas.WishIn,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    db_wish = get_wish(db, current_user, wish_id, write=True)
    check_owner(db, current_user, wish)
    moved = (db_wish.owner_id, db_wish.split_id) != (wish.owner_id, wish.split_id)
    if moved:
        # To the end of the new owner's list
        db_wish.position = next_position(db, models.Wish.position, same_owner(wish.owner_id, wish.split_id))
    for key, value in wish.model_dump().items():
        setattr(db_wish, key, value)
    if wish.split_id and db_wish.family_position is None:
        db_wish.family_position = next_position(db, models.Wish.family_position)
    db.commit()
    db.refresh(db_wish)
    return wish_out(db, current_user, db_wish)


@router.delete("/wishes/{wish_id}")
def delete_wish(
    wish_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    db.delete(get_wish(db, current_user, wish_id, write=True))
    db.commit()
    return {"deleted": wish_id}


def require_parent(user: models.User) -> None:
    if not is_parent(user):
        raise HTTPException(status_code=403, detail="Only parents have a family plan")


@router.get("/wishes/family-plan", response_model=List[schemas.FamilyPlanRow])
def family_plan(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    require_parent(current_user)
    rows, total = [], 0.0
    planned = [w for w in visible_wishes(db, current_user) if w.family_position is not None and not w.bought_on]
    for wish in sorted(planned, key=lambda w: w.family_position or 0):
        out = wish_out(db, current_user, wish)
        total = finance.cents(total + (out["price"] or 0))
        rows.append({**out, "running_total": total})
    return rows


@router.post("/wishes/{wish_id}/move", response_model=schemas.Wish)
def move_wish(
    wish_id: str,
    move: schemas.WishMove,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    family = move.list == "family"
    if family:
        require_parent(current_user)
    # The own list needs the right to change the owner's wishes; the family plan is decided by all parents
    wish = get_wish(db, current_user, wish_id, write=not family)
    if wish.bought_on:
        raise HTTPException(status_code=400, detail="Bought wishes can't be moved")
    key = "family_position" if family else "position"
    if family and wish.family_position is None:
        raise HTTPException(status_code=400, detail="Not in the family plan")
    query = db.query(models.Wish).filter(models.Wish.id != wish.id, models.Wish.bought_on.is_(None))
    if family:
        query = query.filter(models.Wish.family_position.isnot(None))
    else:
        query = query.filter(same_owner(wish.owner_id, wish.split_id))
    # Only wishes the user can see: hidden ones keep their place
    others = [w for w in query if can_see(db, current_user, w.owner_id, w.split_id)]
    mine = getattr(wish, key)
    if move.direction == "up":
        neighbour = max((w for w in others if getattr(w, key) < mine), key=lambda w: getattr(w, key), default=None)
    else:
        neighbour = min((w for w in others if getattr(w, key) > mine), key=lambda w: getattr(w, key), default=None)
    if neighbour:
        setattr(wish, key, getattr(neighbour, key))
        setattr(neighbour, key, mine)
        db.commit()
        db.refresh(wish)
    return wish_out(db, current_user, wish)


@router.post("/wishes/{wish_id}/family-plan", response_model=schemas.Wish)
def add_to_family_plan(
    wish_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    wish = get_wish(db, current_user, wish_id, write=True)
    if wish.family_position is None:
        wish.family_position = next_position(db, models.Wish.family_position)
        db.commit()
        db.refresh(wish)
    return wish_out(db, current_user, wish)


@router.delete("/wishes/{wish_id}/family-plan", response_model=schemas.Wish)
def remove_from_family_plan(
    wish_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    wish = get_wish(db, current_user, wish_id, write=True)
    if wish.split_id:
        raise HTTPException(status_code=400, detail="Common wishes are always in the family plan")
    wish.family_position = None
    db.commit()
    db.refresh(wish)
    return wish_out(db, current_user, wish)


@router.post("/wishes/{wish_id}/bought", response_model=schemas.Wish)
def mark_bought(
    wish_id: str,
    bought: schemas.WishBought,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    wish = get_wish(db, current_user, wish_id, write=True)
    # Positions are kept, so "back to open" returns the wish to its old place
    wish.bought_on = bought.bought_on or date.today()
    db.commit()
    db.refresh(wish)
    return wish_out(db, current_user, wish)


@router.delete("/wishes/{wish_id}/bought", response_model=schemas.Wish)
def mark_open(
    wish_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    wish = get_wish(db, current_user, wish_id, write=True)
    wish.bought_on = None
    db.commit()
    db.refresh(wish)
    return wish_out(db, current_user, wish)
