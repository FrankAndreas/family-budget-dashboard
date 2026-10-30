"""The 🔒 categories in each person's language; the stored (English) name stays the reference (issue #50)."""

from helpers import set_language, BASE_URL, add_transaction, create_account, register

from app import database, models
from app.seed import seed_categories


def german(client, name="mum"):
    headers = register(client, name)
    set_language(headers, "de")
    return headers


def categories(client, headers):
    return client.get(f"{BASE_URL}/categories", headers=headers).json()


def names(client, headers):
    return {c["system_key"]: c["name"] for c in categories(client, headers)}


def test_system_categories_in_the_persons_language(client):
    mum = german(client)
    dad = register(client, "dad")
    assert names(client, mum)["UNSORTED"] == "Unsortiert"
    assert names(client, mum)["SETTLE_UP"] == "Ausgleich"
    assert names(client, dad)["UNSORTED"] == "Unsorted"


def test_logged_out_lists_follow_the_browser(client):
    assert names(client, {"Accept-Language": "de-CH"})["TRANSFER"] == "Umbuchung"


def test_the_familys_own_categories_keep_their_name(client):
    mum = german(client)
    client.post(f"{BASE_URL}/categories", json={"name": "Velo", "type": "EXPENSE"}, headers=mum)
    assert "Velo" in [c["name"] for c in categories(client, mum)]


def preview(client, headers, category):
    csv = f"date,account,category,amount\n2026-10-01,Bank,{category},12.5\n"
    response = client.post(f"{BASE_URL}/import/preview", files={"file": ("a.csv", csv, "text/csv")}, headers=headers)
    return response.json()["rows"][0]


def test_import_accepts_both_names(client):
    mum = german(client)
    create_account(client, mum, "Bank")
    for name in ("Unsortiert", "unsorted", "Unsorted"):
        row = preview(client, mum, name)
        assert row["errors"] == [], row
        # The preview shows the name of the person's language, matching the category list
        assert row["category"] == "Unsortiert"


def test_json_schema_keeps_the_english_names(client):
    mum = german(client)
    schema = client.get(f"{BASE_URL}/import/schema", headers=mum).json()
    enum = schema["properties"]["transactions"]["items"]["properties"]["category"]["enum"]
    assert "Unsorted" in enum and "Unsortiert" not in enum
    assert len(enum) == len(set(enum))
    assert "Unsortiert" not in schema["x-category-types"]


def test_both_names_are_reserved(client):
    mum = german(client)
    for name in ("Ausgleich", "unsorted", "Umbuchung", "Übrige Einnahmen"):
        response = client.post(f"{BASE_URL}/categories", json={"name": name, "type": "EXPENSE"}, headers=mum)
        assert response.status_code == 400, name


def test_report_shows_the_german_name(client):
    mum = german(client)
    account = create_account(client, mum)
    unsorted = next(c["id"] for c in categories(client, mum) if c["system_key"] == "UNSORTED")
    add_transaction(client, mum, account, unsorted, 10)
    report = client.get(f"{BASE_URL}/reports/summary", headers=mum).json()
    assert "Unsortiert" in str(report) and "Unsorted" not in str(report)


def fresh_install():
    models.Base.metadata.drop_all(bind=database.engine)
    models.Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        seed_categories(db)
        return {c.name for c in db.query(models.Category)}


def test_a_new_install_gets_german_categories(monkeypatch):
    monkeypatch.setenv("DEFAULT_LANGUAGE", "de")
    created = fresh_install()
    assert {"Lebensmittel", "Miete", "Auswärts essen", "Rückerstattungen", "Mobilität"} <= created
    assert "Groceries" not in created
    # 🔒 categories keep their English name in the database
    assert {"Unsorted", "Settle up", "Transfer", "Other Income", "Unknown expense"} <= created


def test_an_english_install_keeps_english_categories():
    assert {"Groceries", "Rent"} <= fresh_install()


def test_preview_names_the_files_category_in_the_persons_language(client):
    mum = german(client)
    create_account(client, mum, "Bank")
    row = preview(client, mum, "unsorted")
    # The preview's dropdown and "was <file category>" compare with the category list, which is German
    assert row["file_category"] == "Unsortiert"
    assert preview(client, mum, "Nope")["file_category"] == "Nope"
