"""Receipts kept with their booking (issue #56): photos, PDFs and e-mails.

Files live in ATTACHMENTS_DIR (default: `attachments/` next to the SQLite database), each under its attachment id,
never under the uploaded name. An attachment without a booking is pending: its uploader can still book it; after
24 hours the sweep deletes it, and files whose row is gone (bulk deletes of accounts or people) too.
"""

import email
import hashlib
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from . import auth, database, messages, models, privacy

router = APIRouter()

MAX_BYTES = 10 * 1024 * 1024
PENDING_HOURS = 24
# A file is written a moment before its row is committed; a file without a row is only an orphan after this
ORPHAN_AFTER = timedelta(hours=1)
IMAGES = ("image/jpeg", "image/png")


def directory() -> Path:
    configured = os.getenv("ATTACHMENTS_DIR")
    if configured:
        folder = Path(configured)
    else:
        sqlite_file = make_url(database.SQLALCHEMY_DATABASE_URL).database or "data/budget.db"
        folder = Path(sqlite_file).resolve().parent / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def file_path(attachment_id: str) -> Path:
    return directory() / attachment_id


def detect(data: bytes, filename: str) -> Optional[str]:
    """The file's type from its content (the name only tells an e-mail apart); None if it isn't a receipt type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if filename.lower().endswith(".eml"):
        message = email.message_from_bytes(data)
        if message.get("From") or message.get("Subject"):
            return "message/rfc822"
    return None


def check(data: bytes, filename: str) -> str:
    """The file's type if it can be kept as a receipt; raises a 400 otherwise."""
    if len(data) > MAX_BYTES:
        raise messages.api_error(400, "attachment_too_large")
    content_type = detect(data, filename)
    if not content_type:
        raise messages.api_error(400, "file_type_unsupported")
    return content_type


def store(
    db: Session, owner: models.User, filename: str, data: bytes, transaction_id: Optional[str]
) -> models.Attachment:
    content_type = check(data, filename)
    attachment = models.Attachment(
        transaction_id=transaction_id,
        owner_id=owner.id,
        # Only for display; the file is stored under the id
        filename=os.path.basename(filename or "beleg")[:200],
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_at=datetime.utcnow(),
    )
    db.add(attachment)
    db.flush()
    file_path(attachment.id).write_bytes(data)
    db.commit()
    db.refresh(attachment)
    return attachment


def link(db: Session, user: models.User, transaction: models.Transaction, ids: list[str]) -> None:
    """Attach the user's own pending uploads to a booking."""
    for attachment_id in ids:
        attachment = db.query(models.Attachment).filter(models.Attachment.id == attachment_id).first()
        if not attachment or attachment.owner_id != user.id or attachment.transaction_id is not None:
            raise messages.api_error(400, "attachment_not_found")
        attachment.transaction_id = transaction.id
        booked_from_inbox(db, attachment.sha256)


def booked_from_inbox(db: Session, sha256: str) -> None:
    """A receipt mail (issue #57) or photo (receipt scan) from the inbox is booked: its entry stays as booked (so the
    same one isn't taken again) and its waiting file goes; the booking has it as attachment."""
    mails = db.query(models.InboxMail).filter(models.InboxMail.sha256 == sha256, models.InboxMail.booked_at.is_(None))
    photos = db.query(models.InboxPhoto).filter(
        models.InboxPhoto.sha256 == sha256, models.InboxPhoto.booked_at.is_(None)
    )
    entries: list[models.InboxMail | models.InboxPhoto] = [*mails, *photos]
    for entry in entries:
        entry.booked_at = datetime.utcnow()
        (directory() / "inbox" / entry.id).unlink(missing_ok=True)


def remove_files(ids: list[str]) -> None:
    for attachment_id in ids:
        file_path(attachment_id).unlink(missing_ok=True)


def sweep(db: Session, now: Optional[datetime] = None) -> int:
    """Delete pending attachments older than 24 h, and files without a row (an hour old). Returns how many files
    were removed."""
    cutoff = (now or datetime.utcnow()) - timedelta(hours=PENDING_HOURS)
    old = db.query(models.Attachment).filter(
        models.Attachment.transaction_id.is_(None), models.Attachment.created_at < cutoff
    )
    gone = [attachment.id for attachment in old.all()]
    for attachment in old.all():
        db.delete(attachment)
    db.commit()
    remove_files(gone)
    known = {a.id for a in db.query(models.Attachment.id)}
    return len(gone) + remove_orphans(directory(), known)


def remove_orphans(folder: Path, known: set[str]) -> int:
    """Delete the folder's files whose name is no known id, once they are older than ORPHAN_AFTER (by file time)."""
    cutoff = time.time() - ORPHAN_AFTER.total_seconds()
    removed = 0
    for path in folder.iterdir():
        if path.is_file() and path.name not in known and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def readable(db: Session, user: models.User, attachment_id: str, write: bool = False) -> models.Attachment:
    """The attachment if the user may see (or change) its booking, or it is their own pending upload; else 404."""
    attachment = db.query(models.Attachment).filter(models.Attachment.id == attachment_id).first()
    if attachment and attachment.transaction_id is None and attachment.owner_id == user.id:
        return attachment
    transaction = (
        db.query(models.Transaction).filter(models.Transaction.id == attachment.transaction_id).first()
        if attachment and attachment.transaction_id
        else None
    )
    if not attachment or not transaction or not can_access(db, user, transaction, write):
        raise messages.api_error(404, "attachment_not_found")
    return attachment


def can_access(db: Session, user: models.User, transaction: models.Transaction, write: bool) -> bool:
    account = db.query(models.Account).filter(models.Account.id == transaction.account_id).first()
    owner = db.query(models.User).filter(models.User.id == account.user_id).first() if account else None
    level = privacy.access_level(db, user, owner) if owner else None
    return level is not None and (not write or privacy.can_write(level))


@router.post("/transactions/{transaction_id}/attachments")
async def add_attachment(
    transaction_id: str,
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    transaction = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not transaction or not can_access(db, current_user, transaction, write=True):
        raise messages.api_error(404, "transaction_not_found")
    data = await file.read(MAX_BYTES + 1)
    return out(store(db, current_user, file.filename or "", data, transaction.id))


@router.post("/attachments")
async def add_pending_attachment(
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    """A receipt's file before its booking exists (without the AI); booking it links it, else the sweep removes it."""
    data = await file.read(MAX_BYTES + 1)
    return out(store(db, current_user, file.filename or "", data, None))


@router.get("/attachments/{attachment_id}")
def get_attachment(
    attachment_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> FileResponse:
    attachment = readable(db, current_user, attachment_id)
    # E-mails are only downloaded, never shown: no scripts or tracking images from mails run in the app
    disposition = "attachment" if attachment.content_type == "message/rfc822" else "inline"
    return FileResponse(
        file_path(attachment.id),
        media_type=attachment.content_type,
        filename=attachment.filename,
        content_disposition_type=disposition,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    attachment = readable(db, current_user, attachment_id, write=True)
    db.delete(attachment)
    db.commit()
    remove_files([attachment_id])
    return {"deleted": True}


def out(attachment: models.Attachment) -> dict:
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size": attachment.size,
    }
