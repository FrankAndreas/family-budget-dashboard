"""The AI suggests a category and tags for receipt articles no rule knows (Migros import): only names are sent."""

import json

import pytest

from app import database, models, receipt_ai
from helpers import BASE_URL, register


class Fake:
    def __init__(self, answer=None):
        self.questions: list[str] = []
        self.answer = answer
        self.down = False

    def complete(self, content):
        self.questions.append(content[0]["text"])
        if self.down:
            raise receipt_ai.AiUnavailable("down")
        return self.answer


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setenv("INFOMANIAK_AI_TOKEN", "t")
    monkeypatch.setenv("INFOMANIAK_AI_PRODUCT_ID", "p")
    monkeypatch.delenv("RECEIPT_AI_READS_PER_HOUR", raising=False)
    fake = Fake(
        json.dumps(
            {
                "Zahnpasta": {"category": "Healthcare", "tags": ["Kinder", "Unbekannt"]},
                "Brot": {"category": "Salary", "tags": []},
                "Seife": {"category": "Gibt es nicht", "tags": []},
                "Erfunden": {"category": "Groceries", "tags": []},
            }
        )
    )
    monkeypatch.setattr(receipt_ai, "client_for", lambda settings: fake)
    return fake


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    kinder = client.post(f"{BASE_URL}/tags", json={"name": "Kinder"}, headers=headers).json()["id"]
    return {"headers": headers, "kinder": kinder}


def suggest(names):
    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == "mum").one()
        healthcare = db.query(models.Category).filter(models.Category.name == "Healthcare").one().id
        return receipt_ai.suggest_articles(db, user, names), healthcare


def test_names_and_categories_only_are_sent(client, mum, ai):
    (found, status, _), healthcare = suggest(["Zahnpasta", "Brot", "Seife"])
    assert status == "ok"
    # Unknown or wrong-kind categories, unknown tags and names that weren't asked are dropped
    assert found == {"Zahnpasta": {"category_id": healthcare, "tag_ids": [mum["kinder"]]}}
    [question] = ai.questions
    assert receipt_ai.ARTICLE_MARKER in question
    sent = json.loads(question.split(receipt_ai.ARTICLE_MARKER, 1)[1])
    assert sent == ["Zahnpasta", "Brot", "Seife"]
    assert "Healthcare" in question and "Kinder" in question and "Salary" not in question


def test_off_and_failed(client, mum, ai, monkeypatch):
    ai.down = True
    (found, status, message), _ = suggest(["Zahnpasta"])
    assert (found, status) == ({}, "failed") and message
    monkeypatch.delenv("INFOMANIAK_AI_TOKEN")
    (found, status, _), _ = suggest(["Zahnpasta"])
    assert (found, status) == ({}, "off")


def test_counts_one_read(client, mum, ai, monkeypatch):
    monkeypatch.setenv("RECEIPT_AI_READS_PER_HOUR", "1")
    assert suggest(["Zahnpasta", "Brot"])[0][1] == "ok"
    (found, status, message), _ = suggest(["Zahnpasta"])
    assert (found, status) == ({}, "limit") and message
    assert len(ai.questions) == 1


def test_capped(client, mum, ai, monkeypatch):
    monkeypatch.setattr(receipt_ai, "MAX_TEXTS", 2)
    (_, status, message), _ = suggest(["Zahnpasta", "Brot", "Seife"])
    assert status == "capped" and message
    assert json.loads(ai.questions[0].split(receipt_ai.ARTICLE_MARKER, 1)[1]) == ["Zahnpasta", "Brot"]


def test_fake_client_for_browser_tests(monkeypatch):
    question = receipt_ai.article_prompt(["Healthcare", "Groceries"], [], ["Zahnpasta Kids", "Brot"], "en")
    answer = json.loads(receipt_ai.FakeClient().complete([{"type": "text", "text": question}]))
    assert answer == {
        "Zahnpasta Kids": {"category": "Healthcare", "tags": []},
        "Brot": {"category": "Groceries", "tags": []},
    }
