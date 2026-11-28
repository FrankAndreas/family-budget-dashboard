"""Asking about spending in plain words: the model's query is checked against the family's names, the app computes."""

import json
from datetime import date

import pytest

from app import database, models, reports, spending_ask
from helpers import BASE_URL, admin_headers, add_transaction, category_id, create_account, register, user_id

TODAY = date(2026, 11, 15)
EXPENSE, INCOME = models.CategoryType.EXPENSE, models.CategoryType.INCOME


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(reports, "today", lambda: TODAY)


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    client.post(f"{BASE_URL}/tags", json={"name": "Velo"}, headers=admin_headers(client))
    return {"headers": headers, "account": create_account(client, headers), "id": user_id(client, headers, "mum")}


@pytest.fixture
def db():
    with database.SessionLocal() as session:
        yield session


def book(client, who, category, amount, when, **extra):
    response = add_transaction(
        client, who["headers"], who["account"], category_id(client, category), amount, date=when, **extra
    )
    assert response.status_code == 200, response.text


def answer(**fields):
    query = {"kind": "expense", "category": None, "tag": None, "from": "2026-11", "to": "2026-11", "compare": False}
    return json.dumps({**query, **fields})


def named(db, model, name):
    return db.query(model).filter(model.name == name).one()


class TestParse:
    def test_category_query(self, mum, db):
        query = spending_ask.parse(answer(category="groceries"), db, TODAY)
        assert query == spending_ask.Query(
            EXPENSE, named(db, models.Category, "Groceries"), None, date(2026, 11, 1), date(2026, 11, 1), False
        )

    def test_json_inside_prose(self, mum, db):
        query = spending_ask.parse("Sure:\n```json\n" + answer(category="Groceries") + "\n```", db, TODAY)
        assert query is not None and query.category.name == "Groceries"

    def test_german_default_name(self, mum, db):
        query = spending_ask.parse(answer(category="Lebensmittel"), db, TODAY)
        assert query is not None and query.category.name == "Groceries"

    def test_tag_and_income_and_compare(self, mum, db):
        tag = spending_ask.parse(answer(tag="velo", **{"from": "2026-01", "to": "2026-03"}, compare=True), db, TODAY)
        assert (tag.tag.name, tag.first, tag.last, tag.compare) == ("Velo", date(2026, 1, 1), date(2026, 3, 1), True)
        income = spending_ask.parse(answer(kind="income"), db, TODAY)
        assert (income.kind, income.category, income.tag) == (INCOME, None, None)

    def test_kind_follows_the_category(self, mum, db):
        assert spending_ask.parse(answer(kind="income", category="Groceries"), db, TODAY) is None
        assert spending_ask.parse(answer(category="Salary"), db, TODAY) is None

    def test_extra_keys_are_ignored(self, mum, db):
        query = spending_ask.parse(answer(category="Groceries", bookings=[{"text": "x"}]), db, TODAY)
        assert query is not None and query.category.name == "Groceries"

    @pytest.mark.parametrize(
        "text",
        [
            answer(kind="unknown"),
            answer(category="Yachts"),
            answer(tag="Boat"),
            answer(category="Groceries", tag="Velo"),
            answer(**{"from": "2026-13"}),
            answer(**{"from": "2026-11", "to": "2026-10"}),
            answer(**{"from": "2016-01", "to": "2026-11"}),
            answer(**{"from": "2026-12", "to": "2026-12"}),
            answer(kind="transfers"),
            answer(**{"from": "0000-05", "to": "0000-05"}),
            answer(**{"from": "0001-01", "to": "0001-01"}, compare=True),
            json.dumps({"kind": "expense", "from": "2026-11", "to": "2026-11", "compare": False}),
            "I can't answer that",
            "{not json}",
        ],
    )
    def test_unclear(self, mum, db, text):
        assert spending_ask.parse(text, db, TODAY) is None


class TestTotal:
    def query(self, db, kind=EXPENSE, category=None, tag=None, first=date(2026, 11, 1), last=date(2026, 11, 1)):
        return spending_ask.Query(
            kind,
            named(db, models.Category, category) if category else None,
            named(db, models.Tag, tag) if tag else None,
            first,
            last,
            False,
        )

    def total(self, db, who, query):
        return spending_ask.total(db, who["id"], query, query.first, query.last)

    def test_sums(self, client, mum, db):
        book(client, mum, "Groceries", 50, "2026-11-02")
        book(client, mum, "Groceries", 20, "2026-10-31")
        book(client, mum, "Dining Out", 30, "2026-11-03")
        book(client, mum, "Salary", 5000, "2026-11-01")
        assert self.total(db, mum, self.query(db, category="Groceries")) == 50.0
        assert self.total(db, mum, self.query(db)) == 80.0
        assert self.total(db, mum, self.query(db, category="Groceries", first=date(2026, 10, 1))) == 70.0
        assert self.total(db, mum, self.query(db, kind=INCOME)) == 5000.0
        book(client, mum, "Groceries", 10, "2026-11-04", refund=True)
        assert self.total(db, mum, self.query(db, category="Groceries")) == 40.0

    def test_item_counts_under_its_tag(self, client, mum, db):
        velo = named(db, models.Tag, "Velo").id
        items = [
            {"name": "Velo-Hose", "amount": 80, "category_id": category_id(client, "Clothing"), "tag_ids": [velo]},
            {"name": "Brot", "amount": 5, "category_id": category_id(client, "Groceries")},
        ]
        response = client.post(
            f"{BASE_URL}/transactions",
            json={"account_id": mum["account"], "date": "2026-11-10T12:00:00Z", "items": items},
            headers=mum["headers"],
        )
        assert response.status_code == 200, response.text
        assert self.total(db, mum, self.query(db, tag="Velo")) == 80.0


def test_previous():
    def period(first, last):
        return spending_ask.Query(EXPENSE, None, None, first, last, True)

    assert spending_ask.previous(period(date(2026, 11, 1), date(2026, 11, 1))) == (date(2026, 10, 1), date(2026, 10, 1))
    assert spending_ask.previous(period(date(2026, 1, 1), date(2026, 3, 1))) == (date(2025, 10, 1), date(2025, 12, 1))


def test_prompt():
    text = spending_ask.prompt("Wie viel für Velos?", ["Groceries", "Salary"], ["Velo"], TODAY, "de")
    assert "Groceries" in text and "Salary" in text and "Velo" in text and "2026-11-15" in text
    assert text.endswith(spending_ask.ASK_MARKER + "Wie viel für Velos?")
    assert spending_ask.prompt("q", [], [], TODAY, "en").endswith(spending_ask.ASK_MARKER + "q")


def test_prompt_says_unknown_names_are_unknown():
    assert "not in the lists" in spending_ask.prompt("q", [], [], TODAY, "en")
    assert "nicht in den Listen" in spending_ask.prompt("q", [], [], TODAY, "de")
