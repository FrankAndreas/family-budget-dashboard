"""Article rules: a receipt article's whole name → category and tags (Migros import), learnt from what was booked."""

import pytest
from alembic import command
from sqlalchemy import text
from test_database import sqlite, without_link_checks

from app import article_rules, database, database_setup, models
from helpers import BASE_URL, category_id, register

RULES = f"{BASE_URL}/article-rules"


@pytest.fixture
def mum(client):
    return register(client, "mum")


def tag(client, headers, name):
    return client.post(f"{BASE_URL}/tags", json={"name": name}, headers=headers).json()["id"]


def add(client, headers, name, category="Groceries", tag_ids=()):
    return client.post(
        RULES,
        json={"name": name, "category_id": category_id(client, category), "tag_ids": list(tag_ids)},
        headers=headers,
    )


def test_crud_and_search(client, mum):
    kinder = tag(client, mum, "Kinder")
    created = add(client, mum, "Zahnpasta", "Healthcare", [kinder])
    assert created.status_code == 200, created.text
    rule = created.json()
    assert (rule["name"], rule["category"], rule["tag_ids"]) == ("Zahnpasta", "Healthcare", [kinder])
    add(client, mum, "Brot")
    assert [r["name"] for r in client.get(RULES, params={"q": "zahn"}, headers=mum).json()] == ["Zahnpasta"]
    assert [r["name"] for r in client.get(RULES, headers=mum).json()] == ["Brot", "Zahnpasta"]
    # The same name, written differently
    assert add(client, mum, "zahnpasta ").status_code == 400
    # Only expense categories: articles are costs
    assert add(client, mum, "Lohn", "Salary").status_code == 400
    assert add(client, mum, "Seife", tag_ids=["nope"]).status_code == 400

    body = {"name": "Zahnpasta", "category_id": category_id(client, "Other Expense"), "tag_ids": []}
    changed = client.put(f"{RULES}/{rule['id']}", json=body, headers=mum).json()
    assert (changed["category"], changed["tag_ids"]) == ("Other Expense", [])
    assert client.delete(f"{RULES}/{rule['id']}", headers=mum).status_code == 200
    assert [r["name"] for r in client.get(RULES, headers=mum).json()] == ["Brot"]

    kid = register(client, "kid", role="CHILD", by=mum)
    assert client.get(RULES, headers=kid).status_code == 403
    assert add(client, kid, "Glace").status_code == 403


def test_learn_updates_by_normalised_name(client, mum):
    kinder = tag(client, mum, "Kinder")
    with database.SessionLocal() as db:
        groceries = db.query(models.Category).filter(models.Category.name == "Groceries").one()
        other = db.query(models.Category).filter(models.Category.name == "Other Expense").one()
        article_rules.learn(db, "Brot", groceries, [])
        db.commit()
        article_rules.learn(db, " brot", other, [db.get(models.Tag, kinder)])
        db.commit()
        rules = article_rules.load(db)
        assert list(rules) == ["brot"]
        assert (rules["brot"].name, rules["brot"].category_id, rules["brot"].tag_ids) == ("Brot", other.id, [kinder])


def test_tag_delete_and_usage(client, mum):
    kinder = tag(client, mum, "Kinder")
    rule = add(client, mum, "Windeln", tag_ids=[kinder]).json()
    assert client.get(f"{BASE_URL}/tags/usage", headers=mum).json()[kinder]["article_rules"] == 1
    assert client.delete(f"{BASE_URL}/tags/{kinder}", headers=mum).status_code == 200
    assert client.get(RULES, headers=mum).json()[0]["tag_ids"] == []
    assert client.get(RULES, headers=mum).json()[0]["id"] == rule["id"]


def test_category_in_use(client, mum):
    add(client, mum, "Zahnpasta", "Healthcare")
    usage = client.get(f"{BASE_URL}/categories/usage", headers=mum).json()
    assert usage[category_id(client, "Healthcare")]["article_rules"] == 1


def test_migration_0020_up_and_down(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    database_setup.run(engine, command.downgrade, "0019")
    without_link_checks(
        engine,
        "INSERT INTO tags (id, name) VALUES ('t1', 'Kinder')",
        "INSERT INTO categories (id, name, type) VALUES ('c1', 'Groceries', 'EXPENSE')",
    )
    database_setup.setup(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO article_rules (id, name, name_key, category_id) VALUES ('r1', 'Brot', 'brot', 'c1')"
        )
        conn.exec_driver_sql("INSERT INTO article_rule_tags (rule_id, tag_id) VALUES ('r1', 't1')")
        conn.commit()
        assert conn.execute(text("SELECT count(*) FROM article_rule_tags")).scalar() == 1
    database_setup.run(engine, command.downgrade, "0019")
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
    assert "article_rules" not in tables and "article_rule_tags" not in tables


def test_one_rule_per_name_in_the_database(client, mum):
    # Two imports at the same moment can't both make a rule for the same article
    from sqlalchemy.exc import IntegrityError

    with database.SessionLocal() as db:
        groceries = db.query(models.Category).filter(models.Category.name == "Groceries").one()
        db.add(models.ArticleRule(name="Brot", category_id=groceries.id))
        db.commit()
        db.add(models.ArticleRule(name=" brot", category_id=groceries.id))
        with pytest.raises(IntegrityError):
            db.commit()


def test_migration_0021_keeps_the_first_of_two_rules(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    database_setup.run(engine, command.downgrade, "0020")
    without_link_checks(
        engine,
        "INSERT INTO categories (id, name, type) VALUES ('c1', 'Groceries', 'EXPENSE')",
        "INSERT INTO article_rules (id, name, category_id, created_at) VALUES "
        "('r1', 'Brot', 'c1', '2026-10-01'), ('r2', ' brot', 'c1', '2026-10-02'), ('r3', 'Weißwurst', 'c1', '2026-10-03')",
    )
    database_setup.setup(engine)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name_key FROM article_rules ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [("r1", "brot"), ("r3", "weisswurst")]


def test_renaming_or_recategorising_keeps_the_key(client, mum):
    rule = add(client, mum, "Brot").json()
    body = {"name": "Brot", "category_id": category_id(client, "Other Expense"), "tag_ids": []}
    assert client.put(f"{RULES}/{rule['id']}", json=body, headers=mum).status_code == 200
    body["name"] = "Ruchbrot"
    assert client.put(f"{RULES}/{rule['id']}", json=body, headers=mum).status_code == 200
    assert add(client, mum, "Brot").status_code == 200
    assert add(client, mum, "ruchbrot").status_code == 400
    with database.SessionLocal() as db:
        assert sorted(r.name_key for r in db.query(models.ArticleRule)) == ["brot", "ruchbrot"]
