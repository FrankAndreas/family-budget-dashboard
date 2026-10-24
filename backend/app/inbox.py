"""Receipt mails forwarded by family members (issue #57).

The Cloudflare Email Worker posts a mail here only after Cloudflare found it authentic (dmarc=pass); the app then takes
it only from an address registered for an active person. On arrival just the headers and the MIME structure are read
(sender, subject, date, attachment names): nothing in it is decoded and no AI runs until a parent releases it. The raw
mail waits as a file in ATTACHMENTS_DIR/inbox, a folder of its own so the attachment sweep leaves it alone.
"""

import email
import email.policy
import email.utils
import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from . import attachments, auth, database, emails_api, messages, models, privacy, receipt_ai

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_BYTES = attachments.MAX_BYTES
PATH = "/inbound"
KEEP_DAYS = 30


def inbox_dir() -> Path:
    folder = attachments.directory() / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@dataclass
class MailSummary:
    from_addrs: list[str]
    subject: str
    sent_at: Optional[datetime]
    message_id: str
    attachment_names: list[str]


def clean(text: str, limit: int = 300) -> str:
    """Text a database can store: undecodable bytes become "?"."""
    return text.encode("utf-8", "replace").decode("utf-8", "replace").replace("�", "?").strip()[:limit]


def header(message: email.message.Message, name: str) -> str:
    try:
        return clean(str(message.get(name) or ""))
    except Exception:
        return ""


def summary(raw: bytes) -> MailSummary:
    """The mail's headers and attachment names; the attachments themselves are not decoded."""
    message = email.message_from_bytes(raw, policy=email.policy.default)
    try:
        senders = [str(value) for value in message.get_all("From") or []]
        from_addrs = [address.lower() for _, address in email.utils.getaddresses(senders) if "@" in address]
    except Exception:
        from_addrs = []
    try:
        sent = email.utils.parsedate_to_datetime(header(message, "Date"))
        sent_at: Optional[datetime] = sent.astimezone(timezone.utc).replace(tzinfo=None) if sent.tzinfo else sent
    except Exception:
        sent_at = None
    names = []
    for part in message.walk():
        try:
            name = part.get_filename()
        except Exception:
            name = None
        if name:
            names.append(clean(name, 200))
    message_id = header(message, "Message-ID") or "sha256:" + hashlib.sha256(raw).hexdigest()
    return MailSummary(from_addrs, header(message, "Subject") or "?", sent_at, message_id, names)


def receive(db: Session, raw: bytes) -> Optional[models.InboxMail]:
    """Put the mail in the inbox for the person who forwarded it; None if it is there (or was booked) already."""
    mail = summary(raw)
    person = emails_api.person_for(db, mail.from_addrs[0]) if len(mail.from_addrs) == 1 else None
    if person is None:
        raise messages.api_error(403, "inbound_sender_unknown")
    if db.query(models.InboxMail).filter(models.InboxMail.message_id == mail.message_id).first():
        return None
    entry = models.InboxMail(
        person_id=person.id,
        from_addr=mail.from_addrs[0],
        subject=mail.subject,
        sent_at=mail.sent_at,
        received_at=datetime.utcnow(),
        message_id=mail.message_id,
        attachment_names=mail.attachment_names,
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    db.add(entry)
    db.flush()
    (inbox_dir() / entry.id).write_bytes(raw)
    db.commit()
    return entry


@router.post(PATH)
async def receive_mail(request: Request, db: Session = Depends(database.get_db)) -> dict:
    """Called by the Cloudflare Email Worker with the raw mail; protected by a shared secret, not a login."""
    secret = os.getenv("INBOUND_SECRET", "")
    if not secret:
        raise messages.api_error(503, "inbound_off")
    given = request.headers.get("x-inbound-secret", "")
    if not hmac.compare_digest(given.encode(), secret.encode()):
        logger.warning("%s: wrong or missing secret", PATH)
        raise messages.api_error(401, "inbound_wrong_secret")
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BYTES:
        raise messages.api_error(413, "inbound_too_big")
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise messages.api_error(413, "inbound_too_big")
    try:
        entry = receive(db, raw)
    except Exception:
        # Neither the sender nor the content goes into the log
        logger.warning("%s: mail refused", PATH)
        raise
    if entry is None:
        return {"status": "duplicate"}
    logger.info("%s: mail stored in the inbox", PATH)
    return {"status": "stored", "id": entry.id}


def require_parent(user: models.User) -> None:
    if user.role != models.UserRole.PARENT:
        raise messages.api_error(403, "only_parents_inbox")


def get_entry(db: Session, entry_id: str) -> models.InboxMail:
    entry = (
        db.query(models.InboxMail).filter(models.InboxMail.id == entry_id, models.InboxMail.booked_at.is_(None)).first()
    )
    if not entry:
        raise messages.api_error(404, "inbox_not_found")
    return entry


def writable(db: Session, user: models.User, account: models.Account) -> bool:
    owner = db.query(models.User).filter(models.User.id == account.user_id).first()
    return owner is not None and privacy.can_write(privacy.access_level(db, user, owner))


def suggested_account(db: Session, releaser: models.User, forwarder: Optional[models.User]) -> Optional[str]:
    """The forwarder's account of their latest receipt (a booking with items), else their first bank account (then
    any first account) by name; only if the releasing parent may book on it."""
    if forwarder is None:
        return None
    latest = (
        db.query(models.Transaction)
        .join(models.Account, models.Account.id == models.Transaction.account_id)
        .filter(models.Account.user_id == forwarder.id, models.Transaction.items.any())
        .order_by(models.Transaction.date.desc())
        .first()
    )
    if latest is not None:
        account = db.query(models.Account).filter(models.Account.id == latest.account_id).first()
    else:
        account = (
            db.query(models.Account)
            .filter(models.Account.user_id == forwarder.id)
            .order_by(models.Account.type != models.AccountType.BANK, models.Account.name)
            .first()
        )
    return account.id if account is not None and writable(db, releaser, account) else None


def sweep(db: Session, now: Optional[datetime] = None) -> int:
    """Delete mails nobody released within 30 days, and waiting files without an entry. Returns how many went."""
    cutoff = (now or datetime.utcnow()) - timedelta(days=KEEP_DAYS)
    old = db.query(models.InboxMail).filter(models.InboxMail.booked_at.is_(None), models.InboxMail.received_at < cutoff)
    gone = [entry.id for entry in old.all()]
    for entry in old.all():
        db.delete(entry)
    db.commit()
    removed = len(gone)
    for entry_id in gone:
        (inbox_dir() / entry_id).unlink(missing_ok=True)
    waiting = {e.id for e in db.query(models.InboxMail.id).filter(models.InboxMail.booked_at.is_(None))}
    # Scanned photos share the folder and are never removed here (receipt scan)
    waiting |= {p.id for p in db.query(models.InboxPhoto.id)}
    attachments.remove_orphans(inbox_dir(), waiting)
    return removed


@router.get("/inbox")
def list_inbox(
    current_user: models.User = Depends(auth.get_current_user_from_token), db: Session = Depends(database.get_db)
) -> list[dict]:
    require_parent(current_user)
    entries = (
        db.query(models.InboxMail)
        .filter(models.InboxMail.booked_at.is_(None))
        .order_by(models.InboxMail.received_at.desc())
        .all()
    )
    people = {u.id: u for u in db.query(models.User)}
    rows = []
    for entry in entries:
        forwarder = people.get(entry.person_id or "")
        rows.append(
            {
                "id": entry.id,
                "person_id": entry.person_id,
                "person_name": forwarder.username if forwarder else None,
                "from_addr": entry.from_addr,
                "subject": entry.subject,
                "sent_at": entry.sent_at,
                "received_at": entry.received_at,
                "attachment_names": entry.attachment_names or [],
                "size": entry.size,
                "suggested_account_id": suggested_account(db, current_user, forwarder),
            }
        )
    return rows


@router.delete("/inbox/{entry_id}")
def delete_entry(
    entry_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    require_parent(current_user)
    entry = get_entry(db, entry_id)
    db.delete(entry)
    db.commit()
    (inbox_dir() / entry_id).unlink(missing_ok=True)
    return {"deleted": entry_id}


@router.post("/inbox/{entry_id}/release")
def release(
    entry_id: str,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    """A parent opens the mail: the AI reads it (if set up) into a draft, and it becomes their pending attachment."""
    require_parent(current_user)
    entry = get_entry(db, entry_id)
    raw = (inbox_dir() / entry.id).read_bytes()
    filename = (entry.subject.replace("/", "-").replace("\\", "-")[:100] or "beleg") + ".eml"
    if receipt_ai.Settings.from_env().enabled:
        return receipt_ai.read(db, current_user, filename, raw)
    attachment = attachments.store(db, current_user, filename, raw, None)
    return {"draft": None, "attachment_id": attachment.id, "attachment": attachments.out(attachment)}
