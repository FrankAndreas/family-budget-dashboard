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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from . import attachments, database, emails_api, messages, models

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_BYTES = attachments.MAX_BYTES
PATH = "/inbound"


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
