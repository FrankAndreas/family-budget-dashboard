"""The AI suggests categories for bank rows no rule recognises; only the booking texts are sent (bank import, part 1)."""

import json

import pytest
from test_bank_import import bank_file, line, mum, preview  # noqa: F401 (mum is a fixture)
from test_import import upload
from test_receipt_ai import ai  # noqa: F401 (a fixture)

from app import receipt_ai
from helpers import BASE_URL, category_id


def answer(mapping):
    return "Gerne:\n```json\n" + json.dumps(mapping) + "\n```"


def sent_text(fake):
    [content] = fake.sent
    return " ".join(part["text"] for part in content)


def with_ai(client, headers, content, **data):
    return preview(client, headers, content, ai="1", **data)


def add_rule(client, headers, text, category):
    client.post(
        f"{BASE_URL}/import/rules", json={"text": text, "category_id": category_id(client, category)}, headers=headers
    )


FILE = bank_file(
    line("Einkauf TWINT Muster Stans", "-84.30", saldo="915.70"),
    line("Kiosk Beispiel", "-3.50"),
    line("Kiosk Beispiel", "-4.00", booked="2026-09-02"),
    line("Gutschrift Beispiel AG", "5000"),
)


def test_ai_suggests_for_fallback_rows_only(client, mum, ai):  # noqa: F811
    add_rule(client, mum, "MUSTER", "Groceries")
    ai.answer = answer({"Kiosk Beispiel": "Dining Out", "Gutschrift Beispiel AG": "Salary"})
    result = with_ai(client, mum, FILE)
    assert result["ai"]["status"] == "ok"
    assert result["ai"]["suggestions"] == {
        "3": {"category": "Dining Out", "source": "ai"},
        "4": {"category": "Dining Out", "source": "ai"},
        "5": {"category": "Salary", "source": "ai"},
    }
    rule, kiosk, kiosk2, salary = result["rows"]
    assert (rule["category"], rule["source"]) == ("Groceries", "rule")
    assert (kiosk["category"], kiosk["source"], kiosk2["category"]) == ("Dining Out", "ai", "Dining Out")
    assert (salary["category"], salary["source"]) == ("Salary", "ai")
    text = sent_text(ai)
    assert text.count("Kiosk Beispiel") == 1
    assert "Einkauf TWINT Muster Stans" not in text


def test_only_texts_are_sent(client, mum, ai):  # noqa: F811
    ai.answer = answer({})
    with_ai(client, mum, FILE)
    text = sent_text(ai)
    for secret in ("CH93", "9300762011623852957", "84.30", "915.70", "1000.0", "2026-09", "5000"):
        assert secret not in text


def test_ai_only_when_asked(client, mum, ai):  # noqa: F811
    result = preview(client, mum, FILE)
    assert ai.sent == []
    assert "ai" not in result


def test_ai_off(client, mum, monkeypatch):  # noqa: F811
    monkeypatch.delenv("INFOMANIAK_AI_TOKEN", raising=False)
    result = with_ai(client, mum, FILE)
    assert result["ai"] == {"status": "off", "message": None, "suggestions": {}}
    from app import database, models

    with database.SessionLocal() as db:
        assert db.query(models.ReceiptRead).count() == 0


@pytest.mark.parametrize("failure", ["unavailable", "nonsense"])
def test_ai_failure_keeps_fallback(client, mum, ai, failure):  # noqa: F811
    ai.answer = receipt_ai.AiUnavailable("/chat/completions") if failure == "unavailable" else "no idea"
    result = with_ai(client, mum, FILE)
    assert result["ai"]["status"] == "failed"
    assert result["ai"]["message"] == "The AI couldn't suggest categories this time"
    assert [r["category"] for r in result["rows"]] == ["Unsorted", "Unsorted", "Unsorted", "Other Income"]


def test_ai_limit_keeps_fallback(client, mum, ai, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RECEIPT_AI_READS_PER_HOUR", "1")
    ai.answer = answer({})
    assert with_ai(client, mum, FILE)["ai"]["status"] == "ok"
    result = with_ai(client, mum, FILE)
    assert result["ai"]["status"] == "limit"
    assert "minute" in result["ai"]["message"]
    assert len(ai.sent) == 1


def test_unknown_or_wrong_kind_names_dropped(client, mum, ai):  # noqa: F811
    ai.answer = answer({"Kiosk Beispiel": "Salary", "Einkauf TWINT Muster Stans": "Nonsense", "Other": "Groceries"})
    result = with_ai(client, mum, FILE)
    assert result["ai"]["suggestions"] == {}
    assert result["ai"]["status"] == "ok"


def test_ai_never_suggests_transfer(client, mum, ai):  # noqa: F811
    ai.answer = answer({"Kiosk Beispiel": "Transfer", "Gutschrift Beispiel AG": "Settle up"})
    result = with_ai(client, mum, FILE)
    assert result["ai"]["suggestions"] == {}
    text = sent_text(ai)
    for name in ("Transfer", "Settle up", "Unknown expense", "Unsorted"):
        assert name not in text


def test_german_names(client, mum, ai):  # noqa: F811
    ai.answer = answer({"Kiosk Beispiel": "Auswärts essen"})
    result = with_ai(client, mum, FILE, **{})
    assert result["ai"]["suggestions"]["3"]["category"] == "Dining Out"


def test_capped(client, mum, ai, monkeypatch):  # noqa: F811
    monkeypatch.setattr(receipt_ai, "MAX_TEXTS", 2)
    ai.answer = answer({})
    result = with_ai(client, mum, FILE)
    assert result["ai"]["status"] == "capped"
    assert result["ai"]["message"] == "The AI looked at the first 2 texts; the rest stay unsorted"
    text = sent_text(ai)
    asked = sum(t in text for t in ("Einkauf TWINT Muster Stans", "Kiosk Beispiel", "Gutschrift Beispiel AG"))
    assert asked == 2


def test_ai_suggestion_books_and_can_be_remembered(client, mum, ai):  # noqa: F811
    ai.answer = answer({"Kiosk Beispiel": "Dining Out"})
    suggestions = with_ai(client, mum, FILE)["ai"]["suggestions"]
    changes = {**suggestions, "3": {**suggestions["3"], "remember": "Kiosk"}}
    response = upload(client, mum, FILE, name="export.csv", path="import", changes=json.dumps(changes))
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 4
    rules = client.get(f"{BASE_URL}/import/rules", headers=mum).json()
    assert [(r["text"], r["category"]) for r in rules] == [("Kiosk", "Dining Out")]


def test_already_booked_rows_not_sent(client, mum, ai):  # noqa: F811
    ai.answer = answer({})
    assert upload(client, mum, FILE, name="export.csv", path="import").json()["imported"] == 4
    result = with_ai(client, mum, FILE)
    assert result["duplicates"] == 4
    assert ai.sent == []
    assert result["ai"]["suggestions"] == {}
