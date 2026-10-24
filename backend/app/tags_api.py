"""Tags: what an item is for (Velo, Garten, ...), across categories (issue #56).

Everyone reads them; parents add, rename and delete them (Settings → Tags), like categories.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, database, messages, models, schemas

router = APIRouter()


def require_parent(user: models.User) -> None:
    if user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_tags")


def name_taken(db: Session, name: str, except_id: Optional[str] = None) -> bool:
    return any(t.name.casefold() == name.casefold() and t.id != except_id for t in db.query(models.Tag))


def get_tag(db: Session, tag_id: str) -> models.Tag:
    tag = db.query(models.Tag).filter(models.Tag.id == tag_id).first()
    if not tag:
        raise messages.api_error(404, "tag_not_found")
    return tag


def usage_counts(db: Session) -> dict[str, dict[str, int]]:
    """Per tag: how many items and budgets use it."""
    usage = {t.id: {"items": 0, "budgets": 0} for t in db.query(models.Tag)}
    for tag_id, count in db.query(models.TransactionItemTag.tag_id, func.count()).group_by(
        models.TransactionItemTag.tag_id
    ):
        usage[tag_id]["items"] = count
    for budget_tag_id, count in (
        db.query(models.Budget.tag_id, func.count())
        .filter(models.Budget.tag_id.isnot(None))
        .group_by(models.Budget.tag_id)
    ):
        usage[str(budget_tag_id)]["budgets"] = count
    return usage


@router.get("/tags", response_model=List[schemas.Tag])
def list_tags(_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)):
    return sorted(db.query(models.Tag), key=lambda t: t.name.casefold())


@router.get("/tags/usage")
def tag_usage(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
) -> dict[str, dict[str, int]]:
    require_parent(current_user)
    return usage_counts(db)


@router.post("/tags", response_model=schemas.Tag)
def create_tag(
    tag: schemas.TagCreate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    if name_taken(db, tag.name):
        raise messages.api_error(400, "tag_name_taken")
    db_tag = models.Tag(name=tag.name, icon=tag.icon or None)
    db.add(db_tag)
    db.commit()
    db.refresh(db_tag)
    return db_tag


@router.put("/tags/{tag_id}", response_model=schemas.Tag)
def update_tag(
    tag_id: str,
    update: schemas.TagUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    tag = get_tag(db, tag_id)
    changes = update.model_dump(exclude_unset=True)
    if "name" in changes and name_taken(db, changes["name"], tag.id):
        raise messages.api_error(400, "tag_name_taken")
    for key, value in changes.items():
        setattr(tag, key, value or None if key == "icon" else value)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}")
def delete_tag(
    tag_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    tag = get_tag(db, tag_id)
    if db.query(models.Budget).filter(models.Budget.tag_id == tag.id).count():
        raise messages.api_error(409, "tag_in_budget")
    # Items keep their other tags; the link rows go with the tag (ON DELETE CASCADE)
    db.query(models.TransactionItemTag).filter(models.TransactionItemTag.tag_id == tag.id).delete()
    # Investments with it move to "no tag"
    db.query(models.Asset).filter(models.Asset.tag_id == tag.id).update(
        {models.Asset.tag_id: None}, synchronize_session=False
    )
    db.delete(tag)
    db.commit()
    return {"deleted": True}
