"""Forwarded receipt mails for tests (issue #57), made up here: the repo never holds real mails."""

from email.message import EmailMessage
from typing import Optional

from files import pdf_with_text

from helpers import BASE_URL

SECRET = "test-inbound-secret"


def forwarded(
    sender: str = "mum@example.ch",
    subject: str = "WG: Ihre Bestellung",
    message_id: Optional[str] = "<order-1@example.ch>",
    attachments: Optional[list[tuple[str, bytes, str, str]]] = None,
    body: str = "---------- Weitergeleitete Nachricht ----------\nVon: shop@example.ch\nTotal CHF 12.50\n",
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "invoice@example.ch"
    message["Subject"] = subject
    message["Date"] = "Thu, 22 Oct 2026 18:30:00 +0200"
    if message_id:
        message["Message-ID"] = message_id
    message.set_content(body)
    for name, data, maintype, subtype in attachments or []:
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return bytes(message)


def with_pdf(sender: str = "mum@example.ch", **extra) -> bytes:
    return forwarded(sender, attachments=[("beleg.pdf", pdf_with_text(["Brot 3.50"]), "application", "pdf")], **extra)


def post(client, raw: bytes, secret: Optional[str] = SECRET):
    headers = {"Content-Type": "message/rfc822"}
    if secret is not None:
        headers["X-Inbound-Secret"] = secret
    return client.post(f"{BASE_URL}/inbound", content=raw, headers=headers)
