"""Reading a receipt with the Infomaniak AI service (issue #56).

The file is kept as a pending attachment, turned into AI input (receipt_files.py) and sent with a prompt that lists
only the family's expense category names and tag names. The answer is untrusted: it becomes a draft that the person
checks in the app; nothing is booked here.

The token and the product ID come from the environment and never appear in a response or a log line: errors name
only the API path.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Protocol

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from . import attachments, auth, database, i18n, messages, models, receipt_files

router = APIRouter()
logger = logging.getLogger(__name__)

DEFAULT_MODEL = "google/gemma-4-31B-it"
DEFAULT_READS_PER_HOUR = 30
TIMEOUT_SECONDS = 60
MAX_ITEMS = 100
MAX_NAME = 120
ENDPOINT = "/chat/completions"


@dataclass(frozen=True)
class Settings:
    token: str
    product_id: str
    model: str
    reads_per_hour: int

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.product_id and self.reads_per_hour > 0)

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            reads = int(os.getenv("RECEIPT_AI_READS_PER_HOUR") or DEFAULT_READS_PER_HOUR)
        except ValueError:
            reads = DEFAULT_READS_PER_HOUR
        return cls(
            token=os.getenv("INFOMANIAK_AI_TOKEN", ""),
            product_id=os.getenv("INFOMANIAK_AI_PRODUCT_ID", ""),
            model=os.getenv("RECEIPT_AI_MODEL") or DEFAULT_MODEL,
            reads_per_hour=reads,
        )


class AiUnavailable(Exception):
    """The AI service didn't answer; the message names only the API path."""


class AiClient(Protocol):
    def complete(self, content: list[dict]) -> str: ...


class InfomaniakClient:
    """Infomaniak's OpenAI-compatible chat API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def complete(self, content: list[dict]) -> str:
        base = f"https://api.infomaniak.com/2/ai/{self.settings.product_id}/openai/v1"
        body = {
            "model": self.settings.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}],
        }
        request = urllib.request.Request(
            base + ENDPOINT,
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {self.settings.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                answer = json.load(response)
            return str(answer["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as error:
            # Neither the URL (product ID) nor the error body goes into the log
            logger.warning("AI service %s answered HTTP %s", ENDPOINT, error.code)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            logger.warning("AI service %s not reachable: %s", ENDPOINT, type(error).__name__)
        except ValueError, KeyError, IndexError, TypeError:
            logger.warning("AI service %s sent an unexpected answer", ENDPOINT)
        raise AiUnavailable(ENDPOINT)


class FakeClient:
    """A fixed receipt for the browser tests (RECEIPT_AI_FAKE=1); never used in production."""

    def complete(self, content: list[dict]) -> str:
        return json.dumps(
            {
                "shop": "Migros",
                "date": "2026-10-20",
                "total": 83.40,
                "items": [
                    {"name": "Brot", "amount": 3.50, "category": "Groceries", "tags": []},
                    {"name": "Velo-Hose", "amount": 79.90, "category": "Clothing", "tags": []},
                ],
            }
        )


def client_for(settings: Settings) -> AiClient:
    if os.getenv("RECEIPT_AI_FAKE") == "1":
        return FakeClient()
    return InfomaniakClient(settings)


PROMPTS = {
    "de": """Du liest einen Kassenbeleg aus der Schweiz (Foto, PDF oder E-Mail).
Gib NUR JSON zurück, in genau diesem Format:
{{"shop": "Name des Geschäfts", "date": "YYYY-MM-DD", "total": 0.00,
  "items": [{{"name": "Artikel wie auf dem Beleg", "amount": 0.00, "category": "Kategorie", "tags": ["Tag"]}}]}}
Regeln:
- amount ist der bezahlte Betrag der Zeile in CHF; Rabatte oder Aktionen sind eigene Zeilen mit negativem Betrag.
- category ist genau einer dieser Namen: {categories}
- tags: null bis mehrere dieser Namen, nur wenn sie passen: {tags}
- total ist der Endbetrag des Belegs.
- Lass Kundenkarten-Nummern (Cumulus, Supercard), Kartennummern und Zahlungsdetails weg.""",
    "en": """You read a receipt from Switzerland (photo, PDF or e-mail).
Return ONLY JSON, in exactly this format:
{{"shop": "Name of the shop", "date": "YYYY-MM-DD", "total": 0.00,
  "items": [{{"name": "Item as on the receipt", "amount": 0.00, "category": "Category", "tags": ["Tag"]}}]}}
Rules:
- amount is the line's paid amount in CHF; discounts or promotions are lines of their own with a negative amount.
- category is exactly one of these names: {categories}
- tags: none or several of these names, only when they fit: {tags}
- total is the receipt's final amount.
- Leave out loyalty card numbers (Cumulus, Supercard), card numbers and payment details.""",
}


def prompt(categories: list[str], tags: list[str], lang: str) -> str:
    return PROMPTS.get(lang, PROMPTS["de"]).format(
        categories=", ".join(categories), tags=", ".join(tags) or ("(keine)" if lang == "de" else "(none)")
    )


def amount(value) -> Optional[float]:
    """3.5, "3,50", "CHF 3.50", "-2.00" → a number; None if it isn't one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:[.,]\d+)?", value.replace("'", "").replace("’", ""))
        if match:
            return round(float(match.group(0).replace(",", ".")), 2)
    return None


def parse(text: str, categories: dict[str, str], tags: dict[str, str], unsorted_id: str) -> dict:
    """The AI's answer as a draft with ids: categories and tags by name (ignoring case); raises ValueError."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("not an object")
    items: list[dict[str, Any]] = []
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raw_items = []
    for raw in raw_items[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        raw_tags: list = raw["tags"] if isinstance(raw.get("tags"), list) else []
        tag_ids = [tags[str(t).casefold()] for t in raw_tags if str(t).casefold() in tags]
        items.append(
            {
                "name": str(raw.get("name") or "")[:MAX_NAME].strip() or "?",
                "amount": amount(raw.get("amount")) or 0,
                "category_id": categories.get(str(raw.get("category") or "").casefold(), unsorted_id),
                "tag_ids": list(dict.fromkeys(tag_ids)),
            }
        )
    total = amount(data.get("total"))
    difference = round(total - sum(i["amount"] for i in items), 2) if total is not None else 0
    return {
        "shop": str(data.get("shop") or "")[:MAX_NAME],
        "date": str(data.get("date") or "")[:10],
        "total": total,
        "items": items,
        "difference": difference,
    }


def take_read(db: Session, user_id: str, per_hour: int, now: Optional[datetime] = None) -> None:
    """Count one read for the person, or raise a 429 when they have used up the last hour's reads.

    Reads are kept in the database, so a restart doesn't reset them; reads older than an hour are removed here."""
    now = now or datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    db.query(models.ReceiptRead).filter(models.ReceiptRead.read_at <= hour_ago).delete()
    reads = (
        db.query(models.ReceiptRead.read_at)
        .filter(models.ReceiptRead.user_id == user_id)
        .order_by(models.ReceiptRead.read_at)
        .all()
    )
    if len(reads) >= per_hour:
        db.commit()
        seconds = (reads[0].read_at + timedelta(hours=1) - now).total_seconds()
        minutes = max(1, int(seconds // 60) + 1)
        raise HTTPException(status_code=429, detail=messages.plural("receipt_reads_used_up", minutes))
    db.add(models.ReceiptRead(user_id=user_id, read_at=now))
    db.commit()


@router.get("/receipts/status")
def status(_user: models.User = Depends(auth.get_current_user_from_token)) -> dict:
    return {"enabled": Settings.from_env().enabled}


def read(db: Session, user: models.User, filename: str, data: bytes) -> dict:
    """Read a receipt file with the AI: the draft, and the file kept as the user's pending attachment (its id, and
    how it was stored)."""
    settings = Settings.from_env()
    if not settings.enabled:
        raise messages.api_error(400, "receipt_ai_off")
    # The file is checked before a read is counted or anything is stored
    try:
        content = receipt_files.ai_content(attachments.check(data, filename), data)
    except receipt_files.Unreadable:
        raise messages.api_error(400, "file_type_unsupported")

    expense = [c for c in db.query(models.Category) if c.type == models.CategoryType.EXPENSE]
    category_ids = {name.casefold(): c.id for c in expense for name in i18n.all_names(c)}
    shown = sorted({i18n.category_name(c) for c in expense}, key=str.casefold)
    all_tags = db.query(models.Tag).all()
    unsorted = next((c.id for c in expense if c.system_key == "UNSORTED"), expense[0].id if expense else "")

    take_read(db, user.id, settings.reads_per_hour)
    # Kept as a pending attachment: booking the receipt links it, otherwise the sweep removes it after a day
    attachment = attachments.store(db, user, filename, data, None)
    question = [{"type": "text", "text": prompt(shown, sorted(t.name for t in all_tags), i18n.current())}]
    try:
        answer = client_for(settings).complete(question + content)
    except AiUnavailable:
        raise messages.api_error(502, "receipt_ai_unavailable")
    try:
        draft = parse(answer, category_ids, {t.name.casefold(): t.id for t in all_tags}, unsorted)
    except ValueError, json.JSONDecodeError:
        raise messages.api_error(502, "receipt_ai_unreadable")
    return {"draft": draft, "attachment_id": attachment.id, "attachment": attachments.out(attachment)}


@router.post("/receipts/read")
async def read_receipt(
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    if not Settings.from_env().enabled:
        raise messages.api_error(400, "receipt_ai_off")
    data = await file.read(attachments.MAX_BYTES + 1)
    # The AI answers within seconds, synchronously: in the thread pool, so other requests are served meanwhile
    return await run_in_threadpool(read, db, current_user, file.filename or "", data)
