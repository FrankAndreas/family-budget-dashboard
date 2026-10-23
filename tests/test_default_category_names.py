"""The default categories (Groceries, Salary, ...) in each person's language until a parent renames them; the import,
the AI and the name check accept both names."""

from alembic import command
from sqlalchemy import text

from helpers import BASE_URL, create_account, register

from app import database, database_setup, models, seed
from test_database import sqlite, without_link_checks


def german(client, name="mum"):
    headers = register(client, name)
    client.patch(f"{BASE_URL}/me/language", json={"language": "de"}, headers=headers)
    return headers


def by_key(client, headers):
    return {c["default_key"]: c for c in client.get(f"{BASE_URL}/categories", headers=headers).json()}


def test_defaults_in_the_persons_language(client):
    mum, dad = german(client), register(client, "dad")
    assert by_key(client, mum)["GROCERIES"]["name"] == "Lebensmittel"
    assert by_key(client, mum)["SALARY"]["name"] == "Lohn"
    assert by_key(client, dad)["GROCERIES"]["name"] == "Groceries"


def test_every_default_has_a_key_and_both_names():
    keyed = [c for c in seed.DEFAULT_CATEGORIES if not c.get("system_key")]
    assert all(c["default_key"] in seed.i18n.DEFAULT_NAMES for c in keyed)
    assert all(set(names) == {"en", "de"} for names in seed.i18n.DEFAULT_NAMES.values())


def rename(client, headers, category_id, name):
    return client.put(f"{BASE_URL}/categories/{category_id}", json={"name": name}, headers=headers)


def test_a_renamed_default_keeps_the_familys_name(client):
    mum, dad = german(client), register(client, "dad")
    groceries = by_key(client, mum)["GROCERIES"]
    assert rename(client, mum, groceries["id"], "Essen").status_code == 200
    names = {c["id"]: c["name"] for c in client.get(f"{BASE_URL}/categories", headers=dad).json()}
    assert names[groceries["id"]] == "Essen"
    assert "GROCERIES" not in by_key(client, dad)


def test_saving_the_shown_name_is_no_rename(client):
    """The edit form sends the name it shows (German); that keeps the category translated."""
    mum, dad = german(client), register(client, "dad")
    groceries = by_key(client, mum)["GROCERIES"]
    response = client.put(
        f"{BASE_URL}/categories/{groceries['id']}", json={"name": "Lebensmittel", "icon": "🥖"}, headers=mum
    )
    assert response.status_code == 200 and response.json()["name"] == "Lebensmittel"
    assert by_key(client, dad)["GROCERIES"]["name"] == "Groceries"
    assert by_key(client, dad)["GROCERIES"]["icon"] == "🥖"


def test_both_names_are_reserved(client):
    mum = german(client)
    for name in ("Lebensmittel", "groceries", "Lohn"):
        response = client.post(f"{BASE_URL}/categories", json={"name": name, "type": "EXPENSE"}, headers=mum)
        assert response.status_code == 400, name


def preview(client, headers, category):
    csv = f"date,account,category,amount\n2026-10-01,Bank,{category},12.5\n"
    response = client.post(f"{BASE_URL}/import/preview", files={"file": ("a.csv", csv, "text/csv")}, headers=headers)
    return response.json()["rows"][0]


def test_import_accepts_both_names(client):
    mum = german(client)
    create_account(client, mum, "Bank")
    for name in ("Groceries", "Lebensmittel"):
        row = preview(client, mum, name)
        assert row["errors"] == [] and row["category"] == "Lebensmittel", row


def test_export_uses_the_persons_language(client):
    import csv
    import io
    import zipfile

    mum = german(client)
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"{BASE_URL}/export/analysis.zip", headers=mum).content))
    names = [row["name"] for row in csv.DictReader(io.StringIO(archive.read("categories.csv").decode("utf-8-sig")))]
    assert "Lebensmittel" in names and "Unsortiert" in names and "Groceries" not in names


def test_a_new_german_install_stores_german_names_with_keys(monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "de")
    with database.SessionLocal() as db:
        db.query(models.Category).delete()
        db.commit()
        seed.seed_categories(db)
        groceries = db.query(models.Category).filter(models.Category.default_key == "GROCERIES").one()
        assert groceries.name == "Lebensmittel"


def test_migration_gives_untouched_defaults_their_key(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    database_setup.run(engine, command.downgrade, "0009")
    without_link_checks(
        engine,
        "INSERT INTO categories (id, name, type) VALUES "
        # An old English install, a German one, a renamed default, and a clash (both names exist)
        "('c1', 'Groceries', 'EXPENSE'), ('c2', 'Lohn', 'INCOME'), ('c3', 'Essen', 'EXPENSE'), "
        "('c4', 'Clothing', 'EXPENSE'), ('c5', 'Kleidung', 'EXPENSE')",
    )
    database_setup.setup(engine)
    with engine.connect() as conn:
        keys = dict(conn.execute(text("SELECT id, default_key FROM categories")).all())
    assert keys == {"c1": "GROCERIES", "c2": "SALARY", "c3": None, "c4": None, "c5": None}
