"""What the AI gets from a receipt file (issue #56), as OpenAI-style content parts.

- photo: the image, shrunk to at most 1600 px as JPEG;
- PDF: its text when it has a text layer, otherwise its pages as images (at most 5);
- e-mail: its text (HTML reduced to text, without scripts or styles); when the text has no amounts, its first PDF or
  image attachment instead.

Texts go without e-mail addresses, phone numbers and the From/To lines of a forwarded mail: the AI doesn't need them to
read a receipt (2026-10-24 review). Street addresses and what an image shows still go as they are.
"""

import base64
import email
import email.policy
import io
import re
from email.message import Message
from html.parser import HTMLParser
from typing import Optional

import pypdf
import pypdfium2
from PIL import Image

MAX_SIDE = 1600
MAX_PAGES = 5
# "12.50", "3,50": a receipt's text has amounts
AMOUNT = re.compile(r"\d[.,]\d\d\b")
# Who wrote to whom in a forwarded mail ("Von: Max Muster <max@example.ch>")
HEADER_LINE = re.compile(r"^[ \t>]*(from|to|cc|bcc|reply-to|von|an|kopie|antwort an|de|à)[ \t]*:.*$", re.I | re.M)
MAIL_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Swiss numbers: +41 79 123 45 67, 0041 44 123 45 67, 044 123 45 67
PHONE = re.compile(r"(?:(?:\+|\b00)41[ \t]?|\b0)\d\d[ \t]?\d{3}[ \t]?\d\d[ \t]?\d\d\b")


class Unreadable(Exception):
    """Nothing in the file the AI could read."""


def image_part(image: Image.Image) -> dict:
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    url = "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()
    return {"type": "image_url", "image_url": {"url": url}}


def without_personal(text: str) -> str:
    text = HEADER_LINE.sub("", text)
    return PHONE.sub("[Tel.]", MAIL_ADDRESS.sub("[E-Mail]", text))


def text_part(text: str) -> dict:
    return {"type": "text", "text": without_personal(text).strip()}


def pdf_parts(data: bytes) -> list[dict]:
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:MAX_PAGES])
    except Exception:
        text = ""
    # A text layer with an amount, or a fair amount of text, is read as text (cheaper and exact)
    if AMOUNT.search(text) or len(re.sub(r"\s", "", text)) > 20:
        return [text_part(text)]
    try:
        document = pypdfium2.PdfDocument(data)
        pages = [document[i].render(scale=150 / 72).to_pil() for i in range(min(len(document), MAX_PAGES))]
    except Exception as error:
        raise Unreadable from error
    if not pages:
        raise Unreadable
    return [image_part(page) for page in pages]


class TextOnly(HTMLParser):
    """The visible text of an HTML mail; scripts and styles are left out."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self.skipping += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.skipping:
            self.skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def html_text(html: str) -> str:
    parser = TextOnly()
    parser.feed(html)
    return re.sub(r"\n\s*\n+", "\n", "".join(parser.parts))


def mail_text(message: Message) -> str:
    plain = message.get_body(preferencelist=("plain",)) if hasattr(message, "get_body") else None
    if plain is not None:
        return str(plain.get_content())
    html = message.get_body(preferencelist=("html",)) if hasattr(message, "get_body") else None
    return html_text(html.get_content()) if html is not None else ""


def mail_attachment(message: Message) -> Optional[tuple[str, bytes]]:
    for part in message.walk():
        kind = part.get_content_type()
        if part.get_content_disposition() == "attachment" and kind in ("application/pdf", "image/jpeg", "image/png"):
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                return kind, payload
    return None


def mail_parts(data: bytes) -> list[dict]:
    message = email.message_from_bytes(data, policy=email.policy.default)
    text = mail_text(message).strip()
    if not AMOUNT.search(text):
        attached = mail_attachment(message)
        if attached:
            return ai_content(*attached)
    if not text:
        raise Unreadable
    return [text_part(text)]


def ai_content(content_type: str, data: bytes) -> list[dict]:
    """The file as content parts for the AI; raises Unreadable when there is nothing to read."""
    if content_type in ("image/jpeg", "image/png"):
        try:
            return [image_part(Image.open(io.BytesIO(data)))]
        except Exception as error:
            raise Unreadable from error
    if content_type == "application/pdf":
        return pdf_parts(data)
    if content_type == "message/rfc822":
        return mail_parts(data)
    raise Unreadable
