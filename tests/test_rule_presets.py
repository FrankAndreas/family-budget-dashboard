"""Suggested import rules for Swiss shops, and the categories Sport and Communication (bank import, part 1)."""

from helpers import BASE_URL, category_id, create_account, register
from test_import_rules import csv, rows

from app import database, models, rule_presets

PRESETS = f"{BASE_URL}/import/rules/presets"
RULES = f"{BASE_URL}/import/rules"


def older_family():
    """A family from before Sport and Communication were default categories."""
    with database.SessionLocal() as db:
        db.query(models.Category).filter(models.Category.default_key.in_(rule_presets.NEW_CATEGORIES)).delete()
        db.commit()


def test_presets_button(client):
    mum = register(client, "mum")
    older_family()
    response = client.post(PRESETS, headers=mum)
    assert response.status_code == 200, response.text
    assert response.json() == {"rules": len(rule_presets.PRESETS), "categories": 2}
    texts = {r["text"]: r["category"] for r in client.get(RULES, headers=mum).json()}
    assert texts["DOSENBACH SPORT"] == "Sport"
    assert texts["SWISSCOM"] == "Communication"
    assert texts["GARAGE WINDLING"] == "Transportation"
    assert client.post(PRESETS, headers=mum).json() == {"rules": 0, "categories": 0}


def test_presets_for_a_new_family(client):
    # Sport and Communication are defaults already
    assert client.post(PRESETS, headers=register(client, "mum")).json()["categories"] == 0


def test_presets_skip_existing_text(client):
    mum = register(client, "mum")
    client.post(RULES, json={"text": "coop", "category_id": category_id(client, "Dining Out")}, headers=mum)
    assert client.post(PRESETS, headers=mum).json()["rules"] == len(rule_presets.PRESETS) - 1
    texts = {r["text"]: r["category"] for r in client.get(RULES, headers=mum).json()}
    assert texts["coop"] == "Dining Out"
    assert "COOP" not in texts


def test_presets_reuse_category_by_name(client):
    mum = register(client, "mum")
    older_family()
    with database.SessionLocal() as db:
        db.add(models.Category(name="Sport", type=models.CategoryType.EXPENSE, is_global=True))
        db.commit()
    assert client.post(PRESETS, headers=mum).json()["categories"] == 1
    with database.SessionLocal() as db:
        sport = db.query(models.Category).filter(models.Category.name == "Sport").all()
        assert len(sport) == 1
        assert sport[0].default_key == "SPORT"


def test_presets_skip_missing_default(client):
    mum = register(client, "mum")
    with database.SessionLocal() as db:
        db.query(models.Category).filter(models.Category.default_key == "CLOTHING").delete()
        db.commit()
    clothing = sum(1 for _, key in rule_presets.PRESETS if key == "CLOTHING")
    assert client.post(PRESETS, headers=mum).json()["rules"] == len(rule_presets.PRESETS) - clothing


def test_presets_parents_only(client):
    mum = register(client, "mum")
    kid = register(client, "kid", role="CHILD", by=mum)
    assert client.post(PRESETS, headers=kid).status_code == 403


def test_new_database_gets_presets(client):
    with database.SessionLocal() as db:
        db.query(models.ImportRule).delete()
        db.query(models.Category).delete()
        db.commit()
        rule_presets.seed_new_database(db)
        assert db.query(models.ImportRule).count() == len(rule_presets.PRESETS)
        assert db.query(models.Category).filter(models.Category.default_key == "COMMUNICATION").count() == 1
        db.query(models.ImportRule).delete()
        db.commit()
        # A later start-up seeds no presets: a family that deleted them keeps them deleted
        rule_presets.seed_new_database(db)
        assert db.query(models.ImportRule).count() == 0


def test_new_categories_in_both_languages(client):
    names = {c["name"] for c in client.get(f"{BASE_URL}/categories", headers={"Accept-Language": "de"}).json()}
    assert {"Sport", "Kommunikation"} <= names
    names = {c["name"] for c in client.get(f"{BASE_URL}/categories").json()}
    assert {"Sport", "Communication"} <= names


def test_presets_categorise_bank_texts(client):
    mum = register(client, "mum")
    create_account(client, mum, "Bank")
    client.post(PRESETS, headers=mum)
    lines = [
        "2026-09-01,Bank,Unsorted,80.00,,Einkauf TWINT Dosenbach Sport Stans,p:1",
        "2026-09-02,Bank,Unsorted,320.00,,LSV CSS Versicherung,p:2",
        "2026-09-03,Bank,Unsorted,59.00,,Dosenbach Kriens,p:3",
        "2026-09-04,Bank,Unsorted,49.00,,Ochsner Shoes Stans,p:4",
    ]
    assert [r["category"] for r in rows(client, mum, csv(*lines))] == ["Sport", "Healthcare", "Clothing", "Clothing"]
