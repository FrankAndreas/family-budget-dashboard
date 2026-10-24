"""Receipts photographed on a parent's phone, a whole pile at a time (receipt scan).

Each photo is uploaded as soon as it is taken and waits in the inbox, next to the forwarded mails, until a parent books
it or deletes it: the paper has been thrown away, so nothing here removes a photo on its own. Opening one makes it the
parent's pending attachment, like releasing a mail; booking that attachment marks the photo booked.

A pile scanned with "Read with AI" off (ai=0) is "manual": never sent to the AI, typed in when checked.
"""

import hashlib
import io
import logging
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image
from sqlalchemy.orm import Session

from . import attachments, auth, database, i18n, inbox, messages, models, receipt_ai

router = APIRouter()
logger = logging.getLogger(__name__)

PHOTOS = "/inbox/photos"
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png"}
# The list's thumbnails are shown at about 50 px; 160 is sharp on a phone's screen too
THUMBNAIL_SIDE = 160


def get_photo(db: Session, photo_id: str) -> models.InboxPhoto:
    photo = (
        db.query(models.InboxPhoto)
        .filter(models.InboxPhoto.id == photo_id, models.InboxPhoto.booked_at.is_(None))
        .first()
    )
    if not photo:
        raise messages.api_error(404, "photo_not_found")
    return photo


def photo_out(db: Session, user: models.User, photo: models.InboxPhoto, duplicate: bool = False) -> dict:
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
        "duplicate": duplicate,
    }


def reading_of(photo: models.InboxPhoto) -> Optional[tuple]:
    """What the AI read that makes a receipt: shop, total and date; None when it didn't read all three."""
    draft = photo.draft or {}
    shop, total, date = str(draft.get("shop") or "").strip().casefold(), draft.get("total"), draft.get("date")
    return (shop, total, date) if shop and total is not None and date else None


def likely_duplicates(db: Session) -> set[str]:
    """Photos that repeat an earlier one, booked or not: the same picture, or the same shop, total and date as read
    by the AI. The earliest stays the original, so deleting a duplicate is always safe."""
    seen_files: set[str] = set()
    seen_readings: set[tuple] = set()
    duplicates: set[str] = set()
    for photo in db.query(models.InboxPhoto).order_by(models.InboxPhoto.taken_at, models.InboxPhoto.id):
        reading = reading_of(photo)
        if photo.sha256 in seen_files or (reading is not None and reading in seen_readings):
            duplicates.add(photo.id)
        seen_files.add(photo.sha256)
        if reading is not None:
            seen_readings.add(reading)
    return duplicates


def file_of(photo: models.InboxPhoto):
    return inbox.inbox_dir() / photo.id


# One reader at a time: the photos are read one after another, never twice at once
reading = threading.Lock()


def resume(db: Session) -> None:
    """After a restart: photos whose reading was cut off are read again."""
    db.query(models.InboxPhoto).filter(models.InboxPhoto.read_state == "reading").update({"read_state": "waiting"})
    db.commit()


def read_into(db: Session, photo: models.InboxPhoto, reader: models.User) -> bool:
    """Read the photo with the AI, counting toward the reader's hourly limit, in their language. True when read; a
    429 (limit used up) is raised for the caller, any other problem leaves the photo failed."""
    settings = receipt_ai.Settings.from_env()
    i18n.set_current(i18n.user_language(reader))
    receipt_ai.take_read(db, reader.id, settings.reads_per_hour)
    try:
        content = receipt_ai.file_content(filename(photo, ""), file_of(photo).read_bytes())
        draft = receipt_ai.ai_draft(db, content)
    except Exception as error:
        # Never left "reading": a failed photo is typed in, and opening it tries once more
        if not isinstance(error, HTTPException):
            logger.exception("Reading a scanned receipt failed")
        photo.read_state = "failed"
        db.commit()
        return False
    photo.read_state, photo.draft = "read", draft
    db.commit()
    return True


def read_waiting() -> int:
    """Read the waiting photos, oldest first, in the background; how many were read. A person whose hourly reads are
    used up is skipped until the next run (every 15 minutes, or a new upload)."""
    if not receipt_ai.Settings.from_env().enabled or not reading.acquire(blocking=False):
        return 0
    done = 0
    used_up: set[str] = set()
    try:
        with database.SessionLocal() as db:
            while True:
                waiting = db.query(models.InboxPhoto).filter(
                    models.InboxPhoto.read_state == "waiting",
                    models.InboxPhoto.booked_at.is_(None),
                    models.InboxPhoto.person_id.is_not(None),
                    models.InboxPhoto.person_id.not_in(used_up),
                )
                photo = waiting.order_by(models.InboxPhoto.taken_at, models.InboxPhoto.id).first()
                if photo is None or photo.person_id is None:
                    return done
                taker = db.get(models.User, photo.person_id)
                if taker is None:
                    used_up.add(photo.person_id)
                    continue
                photo.read_state = "reading"
                db.commit()
                try:
                    done += read_into(db, photo, taker)
                except HTTPException:
                    # The taker's reads are used up: back in line for later
                    photo.read_state = "waiting"
                    db.commit()
                    used_up.add(taker.id)
    except Exception:
        logger.exception("Reading scanned receipts failed")
        return done
    finally:
        reading.release()


@router.post(PHOTOS)
async def upload_photo(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    ai: str = Form(""),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    inbox.require_parent(current_user)
    data = await file.read(attachments.MAX_BYTES + 1)
    if attachments.check(data, file.filename or "") not in IMAGE_TYPES:
        raise messages.api_error(400, "file_type_unsupported")
    photo = models.InboxPhoto(
        person_id=current_user.id,
        taken_at=datetime.utcnow(),
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        read_state="manual" if ai == "0" else "waiting",
    )
    db.add(photo)
    db.flush()
    file_of(photo).write_bytes(data)
    db.commit()
    background.add_task(read_waiting)
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
    duplicates = likely_duplicates(db)
    return [photo_out(db, current_user, photo, photo.id in duplicates) for photo in waiting]


@router.get(PHOTOS + "/{photo_id}/thumbnail")
def photo_thumbnail(
    photo_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> Response:
    """A small copy of the photo for the list, so photos with the same shop and total can be told apart."""
    inbox.require_parent(current_user)
    photo = get_photo(db, photo_id)
    image = Image.open(file_of(photo)).convert("RGB")
    image.thumbnail((THUMBNAIL_SIDE, THUMBNAIL_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=80)
    return Response(
        out.getvalue(),
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
    )


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
async def open_photo(
    photo_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    """A parent checks the photo: its draft (if the AI read it) and the photo as their pending attachment."""
    inbox.require_parent(current_user)
    photo = get_photo(db, photo_id)
    if photo.read_state not in ("read", "manual") and receipt_ai.Settings.from_env().enabled:
        # Not read yet (waiting, failed, or over the limit): one more try, on the opener's reads
        try:
            await run_in_threadpool(read_into, db, photo, current_user)
        except HTTPException:
            pass
    data = file_of(photo).read_bytes()
    draft: Optional[dict] = photo.draft if photo.read_state == "read" else None
    # Opened again (after Skip or Cancel): the same pending attachment, not one more
    attachment = (
        db.query(models.Attachment)
        .filter(
            models.Attachment.owner_id == current_user.id,
            models.Attachment.transaction_id.is_(None),
            models.Attachment.sha256 == photo.sha256,
        )
        .first()
    ) or attachments.store(db, current_user, filename(photo, attachments.detect(data, "") or ""), data, None)
    return {"draft": draft, "attachment_id": attachment.id, "attachment": attachments.out(attachment)}
