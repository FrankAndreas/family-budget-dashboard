"""Investments with several tags: in each tag's group, and in full under each tag in Analytics (migration 0019)."""

from datetime import date

import pytest
from alembic import command
from sqlalchemy import text
from test_database import sqlite, without_link_checks

from app import database_setup, reports
from helpers import BASE_URL, add_transaction, category_id, create_account, register, user_id

ASSETS = f"{BASE_URL}/assets"


@pytest.fixture
def mum(client, monkeypatch):
    monkeypatch.setattr(reports, "today", lambda: date(2026, 10, 15))
    headers = register(client, "mum")
    return {"headers": headers, "id": user_id(client, headers, "mum")}


def tag(client, mum, name):
    return client.post(f"{BASE_URL}/tags", json={"name": name}, headers=mum["headers"]).json()["id"]


def bike(client, mum, tag_ids):
    body = {"name": "Velo", "price": 2400, "purchase_date": "2024-10-01", "lifespan_years": 10}
    return client.post(ASSETS, json=body | {"owner_id": mum["id"], "tag_ids": tag_ids}, headers=mum["headers"])


def test_several_tags_sorted_by_name_without_duplicates(client, mum):
    mobility, hobby = tag(client, mum, "Mobility"), tag(client, mum, "Bike")
    response = bike(client, mum, [mobility, hobby, mobility])
    assert response.status_code == 200, response.text
    assert response.json()["tag_ids"] == [hobby, mobility]
    assert bike(client, mum, [mobility, "nope"]).status_code == 400

    # Edited down to one, then none
    body = response.json() | {"tag_ids": [mobility]}
    edited = client.put(f"{ASSETS}/{body['id']}", json=body, headers=mum["headers"]).json()
    assert edited["tag_ids"] == [mobility]
    body["tag_ids"] = []
    assert client.put(f"{ASSETS}/{body['id']}", json=body, headers=mum["headers"]).json()["tag_ids"] == []


def test_counts_in_full_under_each_tag(client, mum):
    mobility, hobby = tag(client, mum, "Mobility"), tag(client, mum, "Bike")
    velo = bike(client, mum, [mobility, hobby]).json()
    account = create_account(client, mum["headers"], "Konto")
    add_transaction(
        client,
        mum["headers"],
        account,
        category_id(client, "Transportation"),
        150,
        date="2026-10-10T12:00:00Z",
        asset_id=velo["id"],
    )
    summary = client.get(f"{BASE_URL}/reports/summary", params={"range": "month"}, headers=mum["headers"]).json()
    # 2400 over 10 years = 20 a month, under each tag
    assert {row["name"]: (row["amount"], row["set_aside"]) for row in summary["by_tag"]} == {
        "Bike": (150, 20),
        "Mobility": (150, 20),
    }

    usage = client.get(f"{BASE_URL}/tags/usage", headers=mum["headers"]).json()
    assert usage[mobility]["assets"] == usage[hobby]["assets"] == 1


def test_deleting_a_tag_keeps_the_others(client, mum):
    mobility, hobby = tag(client, mum, "Mobility"), tag(client, mum, "Bike")
    velo = bike(client, mum, [mobility, hobby]).json()
    assert client.delete(f"{BASE_URL}/tags/{hobby}", headers=mum["headers"]).status_code == 200
    assert client.get(f"{ASSETS}/{velo['id']}", headers=mum["headers"]).json()["tag_ids"] == [mobility]


def test_migration_keeps_the_tag(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    database_setup.run(engine, command.downgrade, "0018")
    without_link_checks(
        engine,
        "INSERT INTO tags (id, name) VALUES ('t1', 'Mobilität'), ('t2', 'Velo')",
        "INSERT INTO assets (id, name, price, purchase_date, lifespan_years, tag_id, kind) "
        "VALUES ('a1', 'Auto', 100, '2024-01-01', 8, 't1', 'PURCHASE'), "
        "('a2', 'Ski', 100, '2024-01-01', 4, NULL, 'PURCHASE')",
    )
    database_setup.setup(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT asset_id, tag_id FROM asset_tags")).all() == [("a1", "t1")]
        conn.exec_driver_sql("INSERT INTO asset_tags (asset_id, tag_id) VALUES ('a1', 't2')")
        conn.commit()

    # Back down: the first tag by name stays
    database_setup.run(engine, command.downgrade, "0018")
    with engine.connect() as conn:
        assert dict(conn.execute(text("SELECT id, tag_id FROM assets")).all()) == {"a1": "t1", "a2": None}
