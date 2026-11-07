"""Wishes: who sees which (own, shared, the parents' common ones) and how one is shown."""

from typing import Optional

from sqlalchemy.orm import Session

from . import models, privacy
from .privacy import is_parent

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
