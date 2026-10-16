from typing import Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from . import models, messages

# Access rules:
# - Everyone has full access to their own money ("OWN")
# - A parent's money is private; another parent gets "VIEW" or "EDIT" only if it was shared with them
# - A child with own allowance: parents view by default; the child can share "EDIT" with a parent or
#   hide from one ("NONE"); privacy mode hides everything from all parents
# - A dependent child has no money of their own; all parents manage them ("EDIT")
# - Children only see themselves
# The family list itself (names, roles) is visible to all parents, and children see the parents.


def share_level(db: Session, owner_id: str, grantee_id: str) -> Optional[str]:
    share = (
        db.query(models.Share).filter(models.Share.owner_id == owner_id, models.Share.grantee_id == grantee_id).first()
    )
    return share.level.value if share else None


def access_level(db: Session, current_user: models.User, target_user: models.User) -> Optional[str]:
    if target_user.id == current_user.id:
        return "OWN"
    if current_user.role != models.UserRole.PARENT:
        return None
    if target_user.role == models.UserRole.CHILD and not target_user.has_allowance:
        return "EDIT"
    if target_user.role == models.UserRole.CHILD and target_user.privacy_enabled:
        return None
    level = share_level(db, target_user.id, current_user.id)
    if level is None and target_user.role == models.UserRole.CHILD:
        return "VIEW"
    return None if level in (None, "NONE") else level


def can_write(level: Optional[str]) -> bool:
    return level in ("OWN", "EDIT")


def check_user_access(db: Session, current_user: models.User, target_user_id: str, write: bool = False) -> models.User:
    """The target user if the current user may view (or with write=True, manage) their money; 403/404 otherwise."""
    target_user = db.query(models.User).filter(models.User.id == target_user_id).first()
    if not target_user:
        raise messages.api_error(404, "user_not_found")
    level = access_level(db, current_user, target_user)
    if level is None or (write and not can_write(level)):
        raise messages.api_error(status.HTTP_403_FORBIDDEN, "no_access_user")
    return target_user


def check_account_access(
    db: Session, current_user: models.User, account_id: str, write: bool = False
) -> models.Account:
    """The account if the current user may view (or with write=True, change) it; 403/404 otherwise."""
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise messages.api_error(404, "account_not_found")
    owner = db.query(models.User).filter(models.User.id == account.user_id).first()
    level = access_level(db, current_user, owner) if owner else None
    if level is None or (write and not can_write(level)):
        raise messages.api_error(status.HTTP_403_FORBIDDEN, "no_access_account")
    return account


def get_accessible_accounts(db: Session, current_user: models.User) -> list[models.Account]:
    users = db.query(models.User).all()
    user_ids = [user.id for user in users if access_level(db, current_user, user) is not None]
    return db.query(models.Account).filter(models.Account.user_id.in_(user_ids)).all()


def can_list_user(current_user: models.User, target_user: models.User) -> bool:
    """Who appears in the family list: parents see everyone except children with privacy on;
    children see themselves and the parents (to choose whom to share with)."""
    if target_user.id == current_user.id or target_user.role == models.UserRole.PARENT:
        return True
    return current_user.role == models.UserRole.PARENT and not target_user.privacy_enabled


def active_parents(db: Session) -> list[models.User]:
    return (
        db.query(models.User).filter(models.User.role == models.UserRole.PARENT, models.User.is_active.is_(True)).all()
    )
