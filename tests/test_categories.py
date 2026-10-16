"""Managing categories: system keys, seeding, and the Settings API (issue #22)."""

import pytest

from app import database, models, seed
from helpers import BASE_URL, add_transaction, category_id, create_account, register

SYSTEM = {
    "TRANSFER": "Transfer",
    "SETTLE_UP": "Settle up",
    "UNSORTED": "Unsorted",
    "UNKNOWN_EXPENSE": "Unknown expense",
    "OTHER_INCOME": "Other Income",
}


def categories(client):
    return {c["name"]: c for c in client.get(f"{BASE_URL}/categories").json()}


class TestSystemCategories:
    def test_keys_in_the_api(self, client):
        listed = categories(client)
        assert {name: listed[name]["system_key"] for name in SYSTEM.values()} == {v: k for k, v in SYSTEM.items()}
        assert listed["Groceries"]["system_key"] is None

    def test_seeding_keeps_renamed_and_deleted_defaults_away(self, client):
        with database.SessionLocal() as db:
            db.query(models.Category).filter(models.Category.name == "Groceries").one().name = "Lebensmittel"
            db.delete(db.query(models.Category).filter(models.Category.name == "Education").one())
            db.commit()
            assert seed.seed_categories(db) == 0
        names = set(categories(client))
        assert "Lebensmittel" in names and "Groceries" not in names and "Education" not in names

    def test_missing_system_category_is_recreated(self, client):
        with database.SessionLocal() as db:
            db.delete(db.query(models.Category).filter(models.Category.system_key == "UNKNOWN_EXPENSE").one())
            db.commit()
            assert seed.seed_categories(db) == 1
            assert seed.system_category(db, "UNKNOWN_EXPENSE").name == "Unknown expense"

    def test_name_without_key_gets_the_key(self, client):
        with database.SessionLocal() as db:
            row = db.query(models.Category).filter(models.Category.system_key == "UNSORTED").one()
            row.system_key = None
            db.commit()
            seed.seed_categories(db)
            assert db.query(models.Category).filter(models.Category.name == "Unsorted").count() == 1
            assert seed.system_category(db, "UNSORTED").name == "Unsorted"
