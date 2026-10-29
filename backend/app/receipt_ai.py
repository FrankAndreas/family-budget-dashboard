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

from . import article_rules, attachments, auth, database, i18n, messages, models, receipt_files

router = APIRouter()
logger = logging.getLogger(__name__)

DEFAULT_MODEL = "google/gemma-4-31B-it"
DEFAULT_READS_PER_HOUR = 30
TIMEOUT_SECONDS = 60
MAX_ITEMS = 100
MAX_NAME = 120
# Distinct bank texts per upload; more are left to the fallback
MAX_TEXTS = 200
# Where the bank texts start in the prompt (the browser tests' fake client finds them by it)
TEXT_MARKER = "TEXTS:"
# Where the receipt articles start in the prompt (Migros import)
ARTICLE_MARKER = "ARTICLES:"
ENDPOINT = "/chat/completions"
# Money sent to or received from a person: the text carries their name, so it isn't sent (2026-10-24 review)
PERSON_TO_PERSON = re.compile(
    r"\bTWINT\b.*\b(an|von|to|from|gesendet|erhalten|sent|received)\b"
    r"|\b(Überweisung|Zahlung|Dauerauftrag|Gutschrift|Auftrag|Transfer|Payment)[ \t]+(an|von|to|from)\b",
    re.I,
)


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
    """A fixed receipt for the browser tests (RECEIPT_AI_FAKE=1); never used in production. Bank texts: money out
    is Groceries, money in Salary."""

    def complete(self, content: list[dict]) -> str:
        question = content[0].get("text", "") if content else ""
        if ARTICLE_MARKER in question:
            names = json.loads(question.split(ARTICLE_MARKER, 1)[1])
            return json.dumps(
                {n: {"category": "Healthcare" if "zahn" in n.casefold() else "Groceries", "tags": []} for n in names}
            )
        if TEXT_MARKER in question:
            texts = json.loads(question.split(TEXT_MARKER, 1)[1])
            return json.dumps({**{t: "Groceries" for t in texts["out"]}, **{t: "Salary" for t in texts["in"]}})
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


TEXT_PROMPTS = {
    "de": """Du ordnest Buchungstexte eines Schweizer Kontoauszugs Kategorien zu.
Gib NUR JSON zurück: ein Objekt, das jeden Text genau wie angegeben auf einen Kategorienamen abbildet.
- Texte unter "out" (Geld ausgegeben) bekommen genau eine dieser Ausgaben-Kategorien: {expense}
- Texte unter "in" (Geld erhalten) bekommen genau eine dieser Einnahmen-Kategorien: {income}
- Wenn du unsicher bist, lass den Text weg.
""",
    "en": """You assign categories to booking texts from a Swiss bank statement.
Return ONLY JSON: an object mapping each text exactly as given to one category name.
- Texts under "out" (money spent) get exactly one of these expense categories: {expense}
- Texts under "in" (money received) get exactly one of these income categories: {income}
- If you are unsure, leave the text out.
""",
}


def text_prompt(expense: list[str], income: list[str], texts_out: list[str], texts_in: list[str], lang: str) -> str:
    question = TEXT_PROMPTS.get(lang, TEXT_PROMPTS["de"]).format(expense=", ".join(expense), income=", ".join(income))
    return question + TEXT_MARKER + json.dumps({"out": texts_out, "in": texts_in}, ensure_ascii=False)


def parse_texts(
    answer: str,
    allowed_out: dict[str, str],
    allowed_in: dict[str, str],
    texts_out: list[str],
    texts_in: list[str],
) -> dict[str, str]:
    """{text: category name} from the AI's answer; names of the wrong kind or unknown ones are dropped. The allowed
    dicts map every name (casefolded, both languages) to the name to show. Raises ValueError for a broken answer."""
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        raise ValueError("no JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("not an object")
    out: dict[str, str] = {}
    for texts, allowed in ((texts_out, allowed_out), (texts_in, allowed_in)):
        for text in texts:
            name = allowed.get(str(data.get(text) or "").strip().casefold())
            if name:
                out[text] = name
    return out


ARTICLE_PROMPTS = {
    "de": """Du ordnest Artikel von Schweizer Kassenzetteln (Migros) Kategorien und Tags zu.
Gib NUR JSON zurück: ein Objekt, das jeden Artikelnamen genau wie angegeben auf {{"category": "...", "tags": [...]}}
abbildet.
- category ist genau einer dieser Namen: {categories}
- tags: keiner oder mehrere dieser Namen, nur wenn sie passen: {tags}
- Wenn du unsicher bist, lass den Artikel weg.
""",
    "en": """You assign categories and tags to articles from Swiss shop receipts (Migros).
Return ONLY JSON: an object mapping each article name exactly as given to {{"category": "...", "tags": [...]}}.
- category is exactly one of these names: {categories}
- tags: none or several of these names, only when they fit: {tags}
- If you are unsure, leave the article out.
""",
}


def article_prompt(categories: list[str], tags: list[str], names: list[str], lang: str) -> str:
    question = ARTICLE_PROMPTS.get(lang, ARTICLE_PROMPTS["de"]).format(
        categories=", ".join(categories), tags=", ".join(tags) or "-"
    )
    return question + ARTICLE_MARKER + json.dumps(names, ensure_ascii=False)


def parse_articles(
    answer: str, categories: dict[str, str], tags: dict[str, str], names: list[str]
) -> dict[str, dict[str, Any]]:
    """{name: {"category_id", "tag_ids"}} from the AI's answer; the dicts map names (casefolded) to ids. Unknown
    names, categories and tags are dropped. Raises ValueError for a broken answer."""
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        raise ValueError("no JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("not an object")
    found: dict[str, dict[str, Any]] = {}
    for name in names:
        entry = data.get(name)
        if not isinstance(entry, dict):
            continue
        category = categories.get(str(entry.get("category") or "").strip().casefold())
        if not category:
            continue
        raw = entry.get("tags")
        raw_tags: list = raw if isinstance(raw, list) else []
        tag_ids = [tags[str(t).strip().casefold()] for t in raw_tags if str(t).strip().casefold() in tags]
        found[name] = {"category_id": category, "tag_ids": list(dict.fromkeys(tag_ids))}
    return found


def plain_categories(db: Session, kind: models.CategoryType) -> list[models.Category]:
    """The family's own and default categories of a kind; not the ones the app books itself (Unsorted, ...)."""
    return [c for c in db.query(models.Category) if c.type == kind and not c.system_key]


def suggest(
    db: Session, user: models.User, texts_out: list[str], texts_in: list[str]
) -> tuple[dict[str, str], str, Optional[str]]:
    """Categories for bank texts no rule knows: (suggestions, status, message). One call, counted as one read;
    status off / ok / capped / limit / failed. Only the texts and the category names are sent, and not the texts of
    money between people."""
    settings = Settings.from_env()
    if not settings.enabled:
        return {}, "off", None
    texts_out = [t for t in texts_out if not PERSON_TO_PERSON.search(t)]
    texts_in = [t for t in texts_in if not PERSON_TO_PERSON.search(t)]
    status, message = "ok", None
    if len(texts_out) + len(texts_in) > MAX_TEXTS:
        texts_out = texts_out[:MAX_TEXTS]
        texts_in = texts_in[: MAX_TEXTS - len(texts_out)]
        status, message = "capped", messages.text("bank_ai_capped", count=MAX_TEXTS)
    if not texts_out and not texts_in:
        return {}, status, message
    expense, income = plain_categories(db, models.CategoryType.EXPENSE), plain_categories(
        db, models.CategoryType.INCOME
    )

    def allowed(categories):
        return {name.casefold(): i18n.category_name(c) for c in categories for name in i18n.all_names(c)}

    def shown(categories):
        return sorted({i18n.category_name(c) for c in categories}, key=str.casefold)

    try:
        take_read(db, user.id, settings.reads_per_hour)
    except HTTPException as error:
        if error.status_code != 429:
            raise
        return {}, "limit", str(error.detail)
    question = text_prompt(shown(expense), shown(income), texts_out, texts_in, i18n.current())
    try:
        answer = client_for(settings).complete([{"type": "text", "text": question}])
        return parse_texts(answer, allowed(expense), allowed(income), texts_out, texts_in), status, message
    except AiUnavailable, ValueError, json.JSONDecodeError:
        return {}, "failed", messages.text("bank_ai_failed")


def suggest_articles(
    db: Session, user: models.User, names: list[str]
) -> tuple[dict[str, dict[str, Any]], str, Optional[str]]:
    """A category and tags for receipt articles no rule knows: (suggestions, status, message). One call, counted as one
    read; status off / ok / capped / limit / failed. Only the article names and the category and tag names are sent."""
    settings = Settings.from_env()
    if not settings.enabled:
        return {}, "off", None
    status, message = "ok", None
    if len(names) > MAX_TEXTS:
        names = names[:MAX_TEXTS]
        status, message = "capped", messages.text("article_ai_capped", count=MAX_TEXTS)
    if not names:
        return {}, status, message
    expense = plain_categories(db, models.CategoryType.EXPENSE)
    all_tags = db.query(models.Tag).all()
    categories = {name.casefold(): c.id for c in expense for name in i18n.all_names(c)}
    tags = {t.name.casefold(): t.id for t in all_tags}
    try:
        take_read(db, user.id, settings.reads_per_hour)
    except HTTPException as error:
        if error.status_code != 429:
            raise
        return {}, "limit", str(error.detail)
    shown = sorted({i18n.category_name(c) for c in expense}, key=str.casefold)
    question = article_prompt(shown, sorted((t.name for t in all_tags), key=str.casefold), names, i18n.current())
    try:
        answer = client_for(settings).complete([{"type": "text", "text": question}])
        return parse_articles(answer, categories, tags, names), status, message
    except AiUnavailable, ValueError, json.JSONDecodeError:
        return {}, "failed", messages.text("article_ai_failed")


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


def file_content(filename: str, data: bytes) -> list[dict]:
    """The file as the AI's input; a 400 if it isn't a receipt the AI can read."""
    try:
        return receipt_files.ai_content(attachments.check(data, filename), data)
    except receipt_files.Unreadable:
        raise messages.api_error(400, "file_type_unsupported")


def ai_draft(db: Session, content: list[dict]) -> dict:
    """The AI's draft of a receipt (the file as file_content made it), in the current language; a 502 if the AI is
    down or answers nonsense. The caller counts the read."""
    expense = [c for c in db.query(models.Category) if c.type == models.CategoryType.EXPENSE]
    category_ids = {name.casefold(): c.id for c in expense for name in i18n.all_names(c)}
    shown = sorted({i18n.category_name(c) for c in expense}, key=str.casefold)
    all_tags = db.query(models.Tag).all()
    unsorted = next((c.id for c in expense if c.system_key == "UNSORTED"), expense[0].id if expense else "")
    question = [{"type": "text", "text": prompt(shown, sorted(t.name for t in all_tags), i18n.current())}]
    try:
        answer = client_for(Settings.from_env()).complete(question + content)
    except AiUnavailable:
        raise messages.api_error(502, "receipt_ai_unavailable")
    try:
        return parse(answer, category_ids, {t.name.casefold(): t.id for t in all_tags}, unsorted)
    except ValueError, json.JSONDecodeError:
        raise messages.api_error(502, "receipt_ai_unreadable")


def read(db: Session, user: models.User, filename: str, data: bytes) -> dict:
    """Read a receipt file with the AI: the draft, and the file kept as the user's pending attachment (its id, and
    how it was stored)."""
    settings = Settings.from_env()
    if not settings.enabled:
        raise messages.api_error(400, "receipt_ai_off")
    # The file is checked before a read is counted or anything is stored
    content = file_content(filename, data)
    take_read(db, user.id, settings.reads_per_hour)
    # Kept as a pending attachment: booking the receipt links it, otherwise the sweep removes it after a day
    attachment = attachments.store(db, user, filename, data, None)
    draft = article_rules.apply_to_draft(db, ai_draft(db, content))
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
