"""Receipts photographed on a parent's phone, a whole pile at a time (receipt scan).

Each photo is uploaded as soon as it is taken and waits in the inbox, next to the forwarded mails, until a parent books
it or deletes it: the paper has been thrown away, so nothing here removes a photo on its own. Opening one makes it the
parent's pending attachment, like releasing a mail; booking that attachment marks the photo booked.
"""

import hashlib
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from . import attachments, auth, database, inbox, messages, models

router = APIRouter()

PHOTOS = "/inbox/photos"
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png"}


def get_photo(db: Session, photo_id: str) -> models.InboxPhoto:
    photo = (
        db.query(models.InboxPhoto)
        .filter(models.InboxPhoto.id == photo_id, models.InboxPhoto.booked_at.is_(None))
        .first()
    )
    if not photo:
        raise messages.api_error(404, "inbox_not_found")
    return photo


def photo_out(db: Session, user: models.User, photo: models.InboxPhoto) -> dict:
    taker = db.get(models.User, photo.person_id) if photo.person_id else None
    draft = photo.draft or {}
    return {
        "id": photo.id,
        "person_id": photo.person_id,
        "person_name": taker.username if taker else None,
        "taken_at": photo.taken_at,
        "read_state": photo.read_state,
        "shop": draft.get("shop") or None,
        "total": draft.get("total"),
        "suggested_account_id": inbox.suggested_account(db, user, taker),
    }


def file_of(photo: models.InboxPhoto):
    return inbox.inbox_dir() / photo.id


@router.post(PHOTOS)
async def upload_photo(
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    inbox.require_parent(current_user)
    data = await file.read(attachments.MAX_BYTES + 1)
    if attachments.check(data, file.filename or "") not in IMAGE_TYPES:
        raise messages.api_error(400, "file_type_unsupported")
    photo = models.InboxPhoto(
        person_id=current_user.id, taken_at=datetime.utcnow(), size=len(data), sha256=hashlib.sha256(data).hexdigest()
    )
    db.add(photo)
    db.flush()
    file_of(photo).write_bytes(data)
    db.commit()
    return photo_out(db, current_user, photo)


@router.get(PHOTOS)
def list_photos(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
) -> list[dict]:
    inbox.require_parent(current_user)
    waiting = (
        db.query(models.InboxPhoto)
        .filter(models.InboxPhoto.booked_at.is_(None))
        .order_by(models.InboxPhoto.taken_at, models.InboxPhoto.id)
        .all()
    )
    return [photo_out(db, current_user, photo) for photo in waiting]


@router.delete(PHOTOS + "/{photo_id}")
def delete_photo(
    photo_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    inbox.require_parent(current_user)
    photo = get_photo(db, photo_id)
    db.delete(photo)
    db.commit()
    (inbox.inbox_dir() / photo_id).unlink(missing_ok=True)
    return {"deleted": photo_id}


def filename(photo: models.InboxPhoto, content_type: str) -> str:
    return f"beleg-{photo.taken_at:%Y-%m-%d}.{IMAGE_TYPES.get(content_type, 'jpg')}"


@router.post(PHOTOS + "/{photo_id}/open")
def open_photo(
    photo_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    """A parent checks the photo: its draft (if the AI read it) and the photo as their pending attachment."""
    inbox.require_parent(current_user)
    photo = get_photo(db, photo_id)
    data = file_of(photo).read_bytes()
    draft: Optional[dict] = photo.draft if photo.read_state == "read" else None
    attachment = attachments.store(db, current_user, filename(photo, attachments.detect(data, "") or ""), data, None)
    return {"draft": draft, "attachment_id": attachment.id, "attachment": attachments.out(attachment)}
