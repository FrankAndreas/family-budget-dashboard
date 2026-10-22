"""Reading a receipt with the Infomaniak AI (issue #56). The tests never call the real service."""

import json
import logging
import urllib.error

import pytest

from files import image_png, pdf_with_text
from helpers import BASE_URL, admin_headers, category_id, register

from app import receipt_ai

READ = f"{BASE_URL}/receipts/read"
SECRET_TOKEN, SECRET_PRODUCT = "tok-SECRET-123", "pid-SECRET-456"


class Fake:
    """Answers with a fixed text and remembers what it was sent."""

    def __init__(self, answer):
        self.answer, self.sent = answer, []

    def complete(self, content):
        self.sent.append(content)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setenv("INFOMANIAK_AI_TOKEN", SECRET_TOKEN)
    monkeypatch.setenv("INFOMANIAK_AI_PRODUCT_ID", SECRET_PRODUCT)
    monkeypatch.delenv("RECEIPT_AI_READS_PER_HOUR", raising=False)
    receipt_ai.reset_rate_limit()
    fake = Fake("")
    monkeypatch.setattr(receipt_ai, "client_for", lambda settings: fake)
    return fake


def answer(**receipt):
    return "Hier ist der Beleg:\n```json\n" + json.dumps(receipt) + "\n```"


def read(client, headers, data=None, name="beleg.png"):
    return client.post(READ, files={"file": (name, data or image_png())}, headers=headers)


def test_status(client, monkeypatch):
    mum = register(client, "mum")
    monkeypatch.delenv("INFOMANIAK_AI_TOKEN", raising=False)
    assert client.get(f"{BASE_URL}/receipts/status", headers=mum).json() == {"enabled": False}
    monkeypatch.setenv("INFOMANIAK_AI_TOKEN", "t")
    monkeypatch.setenv("INFOMANIAK_AI_PRODUCT_ID", "p")
    assert client.get(f"{BASE_URL}/receipts/status", headers=mum).json() == {"enabled": True}
    monkeypatch.setenv("RECEIPT_AI_READS_PER_HOUR", "0")
    assert client.get(f"{BASE_URL}/receipts/status", headers=mum).json() == {"enabled": False}


def test_reading_is_off_without_config(client, monkeypatch):
    mum = register(client, "mum")
    monkeypatch.delenv("INFOMANIAK_AI_TOKEN", raising=False)
    response = read(client, mum)
    assert response.status_code == 400 and response.json()["detail"] == "Reading receipts is not set up"


def test_draft_with_ids(client, ai):
    admin = admin_headers(client)
    velo = client.post(f"{BASE_URL}/tags", json={"name": "Velo"}, headers=admin).json()["id"]
    ai.answer = answer(
        shop="Migros",
        date="2026-10-20",
        total=83.40,
        items=[
            {"name": "Brot", "amount": "3,50", "category": "groceries", "tags": []},
            {"name": "Velo-Hose", "amount": "CHF 79.90", "category": "Clothing", "tags": ["velo", "Erfunden"]},
        ],
    )
    response = read(client, admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attachment_id"]
    draft = body["draft"]
    assert (draft["shop"], draft["date"], draft["total"], draft["difference"]) == ("Migros", "2026-10-20", 83.40, 0)
    assert [(i["name"], i["amount"], i["category_id"], i["tag_ids"]) for i in draft["items"]] == [
        ("Brot", 3.50, category_id(client, "Groceries"), []),
        ("Velo-Hose", 79.90, category_id(client, "Clothing"), [velo]),
    ]


def test_unknown_category_becomes_unsorted_and_difference(client, ai):
    mum = register(client, "mum")
    ai.answer = answer(
        shop="Coop",
        date="2026-10-20",
        total=10,
        items=[
            {"name": "Ding", "amount": 7, "category": "Erfunden"},
            {"name": "Rabatt", "amount": -1.5, "category": "Groceries"},
            {"name": "Kaputt", "amount": "viel", "category": "Groceries"},
        ],
    )
    draft = read(client, mum).json()["draft"]
    unsorted = next(c["id"] for c in client.get(f"{BASE_URL}/categories").json() if c["system_key"] == "UNSORTED")
    assert draft["items"][0]["category_id"] == unsorted
    assert [i["amount"] for i in draft["items"]] == [7, -1.5, 0]
    assert draft["difference"] == 4.5


def test_malformed_answer(client, ai):
    mum = register(client, "mum")
    ai.answer = "Ich kann das nicht lesen."
    response = read(client, mum)
    assert response.status_code == 502 and response.json()["detail"] == "The AI's answer could not be read"


def test_ai_unavailable(client, ai):
    mum = register(client, "mum")
    ai.answer = receipt_ai.AiUnavailable("/chat/completions")
    response = read(client, mum)
    assert response.status_code == 502 and response.json()["detail"] == "The AI service can't be reached right now"


def test_unsupported_file(client, ai):
    mum = register(client, "mum")
    response = read(client, mum, b"hello", "beleg.txt")
    assert response.status_code == 400 and response.json()["detail"] == "This file can't be read"
    assert ai.sent == []


def test_rate_limit(client, ai, monkeypatch):
    monkeypatch.setenv("RECEIPT_AI_READS_PER_HOUR", "2")
    mum, dad = register(client, "mum"), register(client, "dad")
    ai.answer = answer(
        shop="x", date="2026-10-20", total=1, items=[{"name": "a", "amount": 1, "category": "Groceries"}]
    )
    assert read(client, mum).status_code == 200 and read(client, mum).status_code == 200
    response = read(client, mum)
    assert response.status_code == 429 and response.json()["detail"].startswith("You have used up your receipt reads")
    # Every person has their own allowance
    assert read(client, dad).status_code == 200


def test_only_categories_and_tags_go_to_the_ai(client, ai):
    admin = admin_headers(client)
    client.post(f"{BASE_URL}/tags", json={"name": "Velo"}, headers=admin)
    client.post(f"{BASE_URL}/accounts", json={"name": "Geheimkonto", "type": "BANK"}, headers=admin)
    ai.answer = answer(shop="x", date="2026-10-20", total=1, items=[])
    read(client, admin, pdf_with_text(["Brot 3.50"]), "quittung.pdf")
    sent = json.dumps(ai.sent)
    assert "Groceries" in sent and "Velo" in sent and "Brot 3.50" in sent
    assert "Geheimkonto" not in sent and "Admin" not in sent and "Salary" not in sent


def test_no_secret_in_errors_or_logs(client, monkeypatch, caplog):
    monkeypatch.setenv("INFOMANIAK_AI_TOKEN", SECRET_TOKEN)
    monkeypatch.setenv("INFOMANIAK_AI_PRODUCT_ID", SECRET_PRODUCT)
    receipt_ai.reset_rate_limit()

    def refuse(request, timeout):
        assert request.headers["Authorization"] == f"Bearer {SECRET_TOKEN}"
        assert SECRET_PRODUCT in request.full_url
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(receipt_ai.urllib.request, "urlopen", refuse)
    mum = register(client, "mum")
    with caplog.at_level(logging.DEBUG):
        response = read(client, mum)
    assert response.status_code == 502
    for text in (response.text, caplog.text):
        assert SECRET_TOKEN not in text and SECRET_PRODUCT not in text
    assert "/chat/completions" in caplog.text


def test_answer_parsing_directly():
    categories = {"groceries": "g-id"}
    draft = receipt_ai.parse(
        '{"shop": "A", "date": "2026-10-01", "total": "5.00", "items": ['
        '{"name": "' + "x" * 200 + '", "amount": 5, "category": "Groceries"}]}',
        categories,
        {},
        "u-id",
    )
    assert len(draft["items"][0]["name"]) == 120 and draft["items"][0]["category_id"] == "g-id"
    many = '{"total": 1, "items": [' + ",".join(['{"name": "a", "amount": 0.01, "category": "x"}'] * 150) + "]}"
    assert len(receipt_ai.parse(many, categories, {}, "u-id")["items"]) == 100
