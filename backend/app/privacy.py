from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from . import models, schemas

# Visibility rules:
# - Everyone can see themselves
# - Parents share one household: they see each other and each other's accounts
# - Parents see children unless the child has turned on privacy
# - Children only see themselves


def can_view_user(current_user: models.User, target_user: models.User) -> bool:
    if target_user.id == current_user.id:
        return True
    if current_user.role != models.UserRole.PARENT:
        return False
    if target_user.role == models.UserRole.PARENT:
        return True
    return not target_user.privacy_enabled


def check_account_access(db: Session, current_user: models.User, account_id: str) -> models.Account:
    """
    Check if the current user has access to the specified account.
    Returns the account if access is granted, raises HTTPException otherwise.
    """
    account = db.query(models.Account).filter(models.Account.id == account_id).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account_owner = db.query(models.User).filter(models.User.id == account.user_id).first()
    if account_owner and can_view_user(current_user, account_owner):
        return account

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to access this account"
    )


def check_user_access(db: Session, current_user: models.User, target_user_id: str) -> models.User:
    """
    Check if the current user has access to view the specified user's data.
    Returns the user if access is granted, raises HTTPException otherwise.
    """
    target_user = db.query(models.User).filter(models.User.id == target_user_id).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if can_view_user(current_user, target_user):
        return target_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to access this user's data"
    )


def get_accessible_users(db: Session, current_user: models.User) -> list[models.User]:
    """
    Get all users that the current user has permission to view.
    """
    if current_user.role != models.UserRole.PARENT:
        return [current_user]
    return [user for user in db.query(models.User).all() if can_view_user(current_user, user)]


def get_household_user_ids(db: Session) -> list[str]:
    """The parents, whose accounts and budgets together form the household."""
    return [user.id for user in db.query(models.User.id).filter(models.User.role == models.UserRole.PARENT)]


def get_accessible_accounts(db: Session, current_user: models.User) -> list[models.Account]:
    """
    Get all accounts that the current user has permission to view.
    """
    accessible_users = get_accessible_users(db, current_user)
    user_ids = [user.id for user in accessible_users]

    accounts = db.query(models.Account).filter(models.Account.user_id.in_(user_ids)).all()

    return accounts


def filter_users_by_privacy(users: list[models.User], current_user: models.User) -> list[schemas.User]:
    """
    Filter a list of users based on privacy settings and current user's permissions.
    Returns a list of user schemas that the current user can see.
    """
    return [user for user in users if can_view_user(current_user, user)]
