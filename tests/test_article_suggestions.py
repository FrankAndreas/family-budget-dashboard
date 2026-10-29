"""Article rule suggestions: bookings only propose rules; parents add or ignore them in Settings. Invented data."""

import pytest
from alembic import command
from sqlalchemy import text
from test_database import sqlite, without_link_checks

from app import article_rules, database, database_setup, models
from helpers import BASE_URL, category_id, register

SUGGESTIONS = f"{BASE_URL}/article-rules/suggestions"
RULES = f"{BASE_URL}/article-rules"


@pytest.fixture
def mum(client):
    return register(client, "mum")


def suggest(username, *lines):
    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == username).one()
        made = article_rules.suggest(db, user, list(lines))
        db.commit()
        return made


def listed(client, headers):
    response = client.get(SUGGESTIONS, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def rules(client, headers):
    return {r["name"]: (r["category"], r["tag_ids"]) for r in client.get(RULES, headers=headers).json()}


def test_suggest_one_per_article_latest_wins(client, mum):
    groceries, other = category_id(client, "Groceries"), category_id(client, "Other Expense")
    assert suggest("mum", ("Brot", groceries, []), ("Milch", groceries, [])) == 2
    assert suggest("mum", (" brot", other, [])) == 1
    found = listed(client, mum)
    assert [(s["name"], s["category"], s["rule"]) for s in found] == [
        ("Brot", "Other Expense", None),
        ("Milch", "Groceries", None),
    ]
    assert rules(client, mum) == {}


def test_matching_rule_no_suggestion_differing_rule_suggests(client, mum):
    groceries = category_id(client, "Groceries")
    client.post(RULES, json={"name": "Brot", "category_id": groceries}, headers=mum)
    assert suggest("mum", ("brot", groceries, [])) == 0
    assert listed(client, mum) == []
    kinder = client.post(f"{BASE_URL}/tags", json={"name": "Kinder"}, headers=mum).json()["id"]
    assert suggest("mum", ("Brot", groceries, [kinder])) == 1
    [found] = listed(client, mum)
    assert found["rule"] == {"category": "Groceries", "tag_ids": []}
    assert found["tag_ids"] == [kinder]


def test_child_makes_none(client, mum):
    register(client, "kid", role="CHILD", by=mum)
    assert suggest("kid", ("Glace", category_id(client, "Groceries"), [])) == 0
    assert listed(client, mum) == []
    kid_headers = register(client, "kid2", role="CHILD", by=mum)
    assert client.get(SUGGESTIONS, headers=kid_headers).status_code == 403


def test_add_makes_or_updates_the_rule(client, mum):
    groceries, other = category_id(client, "Groceries"), category_id(client, "Other Expense")
    suggest("mum", ("Brot", other, []), ("Milch", groceries, []))
    # A rule for Brot was made by hand meanwhile: Add updates it, never a second one
    client.post(RULES, json={"name": "brot", "category_id": groceries}, headers=mum)
    by_name = {s["name"]: s["id"] for s in listed(client, mum)}
    response = client.post(f"{SUGGESTIONS}/{by_name['Brot']}/add", json={}, headers=mum)
    assert response.status_code == 200, response.text
    assert client.post(f"{SUGGESTIONS}/{by_name['Milch']}/add", json={}, headers=mum).status_code == 200
    assert rules(client, mum) == {"brot": ("Other Expense", []), "Milch": ("Groceries", [])}
    assert listed(client, mum) == []


def test_add_with_changes(client, mum):
    kinder = client.post(f"{BASE_URL}/tags", json={"name": "Kinder"}, headers=mum).json()["id"]
    suggest("mum", ("Windeln", category_id(client, "Groceries"), []))
    [found] = listed(client, mum)
    body = {"category_id": category_id(client, "Healthcare"), "tag_ids": [kinder]}
    assert client.post(f"{SUGGESTIONS}/{found['id']}/add", json=body, headers=mum).status_code == 200
    assert rules(client, mum) == {"Windeln": ("Healthcare", [kinder])}


def test_add_non_expense_400_keeps_it(client, mum):
    suggest("mum", ("Windeln", category_id(client, "Groceries"), []))
    [found] = listed(client, mum)
    body = {"category_id": category_id(client, "Salary")}
    assert client.post(f"{SUGGESTIONS}/{found['id']}/add", json=body, headers=mum).status_code == 400
    assert len(listed(client, mum)) == 1 and rules(client, mum) == {}


def test_add_all(client, mum):
    groceries = category_id(client, "Groceries")
    suggest("mum", ("Brot", groceries, []), ("Milch", groceries, []))
    response = client.post(f"{SUGGESTIONS}/add-all", headers=mum)
    assert response.status_code == 200 and response.json() == {"added": 2}
    assert set(rules(client, mum)) == {"Brot", "Milch"} and listed(client, mum) == []


def test_ignore(client, mum):
    suggest("mum", ("Brot", category_id(client, "Groceries"), []))
    [found] = listed(client, mum)
    assert client.delete(f"{SUGGESTIONS}/{found['id']}", headers=mum).status_code == 200
    assert listed(client, mum) == [] and rules(client, mum) == {}
    # A later booking may propose it again
    assert suggest("mum", ("Brot", category_id(client, "Groceries"), [])) == 1


def test_tag_and_category_delete(client, mum):
    kinder = client.post(f"{BASE_URL}/tags", json={"name": "Kinder"}, headers=mum).json()["id"]
    ferien = client.post(f"{BASE_URL}/categories", json={"name": "Ferien", "type": "EXPENSE"}, headers=mum).json()["id"]
    suggest("mum", ("Windeln", category_id(client, "Groceries"), [kinder]), ("Sonnencreme", ferien, []))
    assert client.delete(f"{BASE_URL}/tags/{kinder}", headers=mum).status_code == 200
    # A suggestion is only a proposal: it doesn't keep its category from being deleted
    assert client.delete(f"{BASE_URL}/categories/{ferien}", headers=mum).status_code == 200
    assert [(s["name"], s["tag_ids"]) for s in listed(client, mum)] == [("Windeln", [])]


def test_migration_0022(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    without_link_checks(engine, "INSERT INTO categories (id, name, type) VALUES ('c1', 'Groceries', 'EXPENSE')")
    with engine.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO article_rule_suggestions (id, name, name_key, category_id) VALUES ('s1', 'Brot', 'brot', 'c1')"
        )
        conn.commit()
    database_setup.run(engine, command.downgrade, "0021")
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
    assert "article_rule_suggestions" not in tables and "article_rule_suggestion_tags" not in tables
