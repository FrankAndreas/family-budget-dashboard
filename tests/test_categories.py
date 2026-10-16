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


@pytest.fixture
def mum(client):
    return register(client, "mum")


def create(client, headers, name, kind="EXPENSE", icon=None):
    return client.post(f"{BASE_URL}/categories", json={"name": name, "type": kind, "icon": icon}, headers=headers)


def update(client, headers, category, **fields):
    return client.put(f"{BASE_URL}/categories/{category_id(client, category)}", json=fields, headers=headers)


class TestApi:
    def test_create(self, client, mum):
        created = create(client, mum, " Car leasing ", icon="🚙").json()
        assert (created["name"], created["type"], created["icon"], created["system_key"]) == (
            "Car leasing",
            "EXPENSE",
            "🚙",
            None,
        )
        assert create(client, mum, "car LEASING").json()["detail"] == "A category with that name already exists"
        assert create(client, mum, "Moves", "TRANSFER").status_code == 400
        assert create(client, mum, "  ").status_code == 422
        assert create(client, mum, "x" * 51).status_code == 422

    def test_children_cant_manage(self, client, mum):
        kid = register(client, "kid", role="CHILD", by=mum)
        response = create(client, kid, "Games")
        assert response.status_code == 403 and response.json()["detail"] == "Only parents can manage categories"

    def test_rename_a_default(self, client, mum):
        assert update(client, mum, "Groceries", name="Lebensmittel", icon="🥖").status_code == 200
        assert "Lebensmittel" in categories(client)

    def test_system_category_locked_except_icon(self, client, mum):
        locked = "This category is used by the app and can't be changed"
        assert update(client, mum, "Unsorted", name="Misc").json()["detail"] == locked
        assert update(client, mum, "Unsorted", type="INCOME").json()["detail"] == locked
        assert update(client, mum, "Unsorted", icon="🗂️").status_code == 200
        response = client.delete(f"{BASE_URL}/categories/{category_id(client, 'Unsorted')}", headers=mum)
        assert response.status_code == 400 and response.json()["detail"] == locked

    def test_type_change_only_when_unused(self, client, mum):
        assert update(client, mum, "Gift", type="EXPENSE").status_code == 200
        account = create_account(client, mum)
        add_transaction(client, mum, account, category_id(client, "Gift"), 5)
        response = update(client, mum, "Gift", type="INCOME")
        assert response.status_code == 400
        assert response.json()["detail"] == "Used by 1 transaction; its type can't change"

    def test_delete(self, client, mum):
        create(client, mum, "Car leasing")
        assert (
            client.delete(f"{BASE_URL}/categories/{category_id(client, 'Car leasing')}", headers=mum).status_code == 200
        )
        account = create_account(client, mum)
        for _ in range(2):
            add_transaction(client, mum, account, category_id(client, "Clothing"), 5)
        client.post(
            f"{BASE_URL}/budgets", json={"category_id": category_id(client, "Clothing"), "limit": 50}, headers=mum
        )
        response = client.delete(f"{BASE_URL}/categories/{category_id(client, 'Clothing')}", headers=mum)
        assert response.status_code == 409
        assert response.json()["detail"] == "Used by 2 transactions and 1 budget"

    def test_usage(self, client, mum):
        account = create_account(client, mum)
        add_transaction(client, mum, account, category_id(client, "Clothing"), 5)
        usage = client.get(f"{BASE_URL}/categories/usage", headers=mum).json()
        assert usage[category_id(client, "Clothing")] == {
            "transactions": 1,
            "budgets": 0,
            "planned_costs": 0,
            "import_rules": 0,
        }
        assert category_id(client, "Healthcare") not in usage

    def test_features_still_work_after_renames(self, client, mum):
        # Month check books "Unknown expense" by key, and import rules find the fallback by key
        update(client, mum, "Groceries", name="Lebensmittel")
        assert seed_names_resolve()


def seed_names_resolve():
    with database.SessionLocal() as db:
        return all(seed.system_category(db, key) for key in SYSTEM)
