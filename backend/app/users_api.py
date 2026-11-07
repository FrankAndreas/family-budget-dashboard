"""Family members as this app knows them (the hub has name, role and PIN), privacy and sharing."""

from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Request, status
from sqlalchemy.orm import Session

from . import auth, crud, database, hub, hub_people, messages, models, ownership, privacy, schemas
from .privacy import is_dependent, is_parent

router = APIRouter()


@router.get("/users", response_model=List[schemas.User])
def read_users(
    request: Request,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # The people the family hub lists for this app; removed ones stay hidden with their data (spec 2026-10-30). A
    # parent looking at the family (Settings) sees the hub's list as it is now, not up to a minute old
    if is_parent(current_user):
        token, _ = auth.request_token(request)
        try:
            hub_people.refresh(db, token or "", force=True)
        except hub.HubUnavailable:
            raise messages.CodedError(503, "hub_unavailable") from None
    people = db.query(crud.models.User).filter(crud.models.User.is_active.is_(True)).all()
    return [user for user in people if privacy.can_list_user(current_user, user)]


@router.get("/me", response_model=schemas.User)
def read_users_me(current_user: models.User = Depends(auth.get_current_user_from_token)):
    return current_user


@router.put("/users/{user_id}", response_model=schemas.User)
def update_user(
    user_id: str,
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    """What only this app knows about a person: Jugendlohn and privacy. Name, role and PIN are the family hub's."""
    if not is_parent(current_user):
        raise messages.api_error(403, "only_parents_update_users")

    target_user = db.query(crud.models.User).filter(crud.models.User.id == user_id).first()
    if not target_user:
        raise messages.api_error(404, "user_not_found")

    # Privacy is the person's own switch (issue #134): a parent can't end a child's privacy mode
    changes_privacy = (
        user_update.privacy_enabled is not None and user_update.privacy_enabled != target_user.privacy_enabled
    )
    if changes_privacy and target_user.id != current_user.id:
        raise messages.api_error(403, "own_privacy_only")

    if user_update.has_allowance is not None and user_update.has_allowance != target_user.has_allowance:
        if target_user.role != models.UserRole.CHILD:
            raise messages.api_error(400, "allowance_children_only")
        if not user_update.has_allowance and crud.get_accounts(db, user_id):
            raise messages.api_error(400, "delete_child_accounts_first")

    return crud.update_user(db, user_id, user_update)


@router.get("/hub")
def hub_login():
    """Where the browser logs in (the family hub), for a visitor without a login."""
    return {"login_url": hub.client.public_url()}


@router.get("/users/removed", response_model=List[schemas.RemovedUser])
def removed_users(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    """People the family hub no longer lists for this app: their data is kept until a parent deletes it here."""
    if not is_parent(current_user):
        raise messages.api_error(403, "only_parents_delete_users")
    return (
        db.query(crud.models.User)
        .filter(crud.models.User.is_active.is_(False))
        .order_by(crud.models.User.username)
        .all()
    )


@router.delete("/users/{user_id}", response_model=schemas.User)
def delete_user(
    user_id: str,
    removal: Optional[schemas.MemberRemoval] = Body(default=None),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if not is_parent(current_user):
        raise messages.api_error(403, "only_parents_delete_users")

    user_to_delete = db.query(crud.models.User).filter(crud.models.User.id == user_id).first()
    if not user_to_delete:
        raise messages.api_error(404, "user_not_found")
    # Only people the family hub no longer lists: an active family member's data is never deleted by mistake
    if user_to_delete.is_active:
        raise messages.api_error(409, "still_in_hub")

    # Their investments and yearly bills go where the parent decided (409 lists any without a decision)
    ownership.apply_item_decisions(db, user_id, removal.items if removal else [])
    return crud.delete_user(db, user_id)


@router.patch("/me/privacy")
def update_privacy(
    privacy_update: dict,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    # Only children can update their own privacy settings
    if current_user.role != models.UserRole.CHILD:
        raise messages.api_error(status.HTTP_403_FORBIDDEN, "privacy_children_only")

    current_user.privacy_enabled = privacy_update.get("privacy_enabled", current_user.privacy_enabled)
    db.commit()
    db.refresh(current_user)
    return {"message": "Privacy settings updated", "privacy_enabled": current_user.privacy_enabled}


# Sharing: who sees whose money
@router.get("/shares", response_model=List[schemas.Share])
def get_shares(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    # What the current user shared, and what was shared with them; not with people removed in the hub
    shares = (
        db.query(models.Share)
        .filter((models.Share.owner_id == current_user.id) | (models.Share.grantee_id == current_user.id))
        .all()
    )
    active = {u.id for u in db.query(models.User).filter(models.User.is_active.is_(True))}
    return [s for s in shares if s.owner_id in active and s.grantee_id in active]


@router.put("/shares/{grantee_id}")
def set_share(
    grantee_id: str,
    share: schemas.ShareSet,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    if is_dependent(current_user):
        raise messages.api_error(403, "nothing_to_share_without_allowance")
    grantee = db.query(models.User).filter(models.User.id == grantee_id).first()
    if not grantee or not is_parent(grantee) or grantee.id == current_user.id:
        raise messages.api_error(400, "share_with_parent_only")
    crud.set_share(db, current_user, grantee_id, share.level)
    return {"level": share.level}
