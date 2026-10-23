"""The family members' e-mail addresses (issue #57): a receipt mail is taken only from one of them.

Parents manage them in Settings → Family; a person can have several, an address belongs to one person.
"""

import re
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, database, messages, models, schemas

router = APIRouter()

ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def require_parent(user: models.User) -> None:
    if user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_emails")


def normalize(address: str) -> str:
    return address.strip().lower()


def person_for(db: Session, address: str) -> Optional[models.User]:
    """The active person the address is registered for, if any."""
    row = db.query(models.UserEmail).filter(models.UserEmail.address == normalize(address)).first()
    if not row:
        return None
    person = db.query(models.User).filter(models.User.id == row.user_id).first()
    return person if person and person.is_active is not False else None


@router.get("/emails", response_model=List[schemas.Email])
def list_emails(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
):
    require_parent(current_user)
    return db.query(models.UserEmail).order_by(models.UserEmail.address).all()


@router.post("/users/{user_id}/emails", response_model=schemas.Email)
def add_email(
    user_id: str,
    email: schemas.EmailCreate,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
):
    require_parent(current_user)
    if not db.query(models.User).filter(models.User.id == user_id).first():
        raise messages.api_error(404, "user_not_found")
    address = normalize(email.address)
    if not ADDRESS.match(address):
        raise messages.api_error(400, "email_invalid")
    if db.query(models.UserEmail).filter(models.UserEmail.address == address).first():
        raise messages.api_error(400, "email_taken")
    row = models.UserEmail(user_id=user_id, address=address)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/emails/{email_id}")
def delete_email(
    email_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    require_parent(current_user)
    row = db.query(models.UserEmail).filter(models.UserEmail.id == email_id).first()
    if not row:
        raise messages.api_error(404, "email_not_found")
    db.delete(row)
    db.commit()
    return {"deleted": email_id}
