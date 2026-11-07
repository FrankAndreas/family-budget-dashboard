"""Family members' e-mail addresses: which person a receipt mail comes from."""

from typing import Optional

from sqlalchemy.orm import Session

from . import models


def normalize(address: str) -> str:
    return address.strip().lower()


def person_for(db: Session, address: str) -> Optional[models.User]:
    """The active person the address is registered for, if any."""
    row = db.query(models.UserEmail).filter(models.UserEmail.address == normalize(address)).first()
    if not row:
        return None
    person = db.query(models.User).filter(models.User.id == row.user_id).first()
    return person if person and person.is_active is not False else None
