"""POST /reports/ask: a question about spending in plain words (design 2026-11-27); the rules are in spending_ask."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from . import auth, database, i18n, messages, models, privacy, receipt_ai, reports, spending_ask

router = APIRouter()


class Question(BaseModel):
    question: str = Field(max_length=spending_ask.MAX_QUESTION)
    user_id: Optional[str] = None

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty question")
        return value


def month_text(day: date) -> str:
    return day.strftime("%Y-%m")


@router.post("/reports/ask")
def ask(
    body: Question,
    current_user: models.User = Depends(auth.get_current_user_from_token),
    db: Session = Depends(database.get_db),
) -> dict:
    settings = receipt_ai.Settings.from_env()
    if not settings.enabled:
        raise messages.api_error(400, "ask_off")
    owner = privacy.check_user_access(db, current_user, body.user_id) if body.user_id else current_user
    receipt_ai.take_read(db, current_user.id, settings.reads_per_hour, key="ask_used_up")
    today = reports.today()
    kinds = (models.CategoryType.EXPENSE, models.CategoryType.INCOME)
    categories = sorted({i18n.category_name(c) for c in db.query(models.Category) if c.type in kinds}, key=str.casefold)
    tags = sorted((t.name for t in db.query(models.Tag)), key=str.casefold)
    text = spending_ask.prompt(body.question, categories, tags, today, i18n.current())
    try:
        answer = receipt_ai.client_for(settings).complete([{"type": "text", "text": text}], schema=spending_ask.SCHEMA)
    except receipt_ai.AiUnavailable:
        raise messages.api_error(502, "ask_ai_unavailable")
    query = spending_ask.parse(answer, db, today)
    if query is None:
        return {"status": "unclear", "message": messages.text("ask_unclear")}
    compare = None
    if query.compare:
        first, last = spending_ask.previous(query)
        compare = {
            "from": month_text(first),
            "to": month_text(last),
            "amount": spending_ask.total(db, owner.id, query, first, last),
        }
    return {
        "status": "ok",
        "kind": "income" if query.kind == models.CategoryType.INCOME else "expense",
        "category": i18n.category_name(query.category) if query.category else None,
        "tag": query.tag.name if query.tag else None,
        "from": month_text(query.first),
        "to": month_text(query.last),
        "amount": spending_ask.total(db, owner.id, query, query.first, query.last),
        "compare": compare,
    }
