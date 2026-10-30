"""Tags: what an item is for, across categories (issue #56). Everyone reads them, parents manage them."""

from datetime import datetime

from helpers import set_language, BASE_URL, admin_headers, create_account, register, user_id

from app import database, models

TAGS = f"{BASE_URL}/tags"


def add(client, headers, name, icon=None):
    return client.post(TAGS, json={"name": name, "icon": icon}, headers=headers)


def test_add_and_list_sorted(client):
    admin = admin_headers(client)
    add(client, admin, "Velo", "🚲")
    add(client, admin, "  Garten ")
    kid = register(client, "kid", role="CHILD")
    tags = client.get(TAGS, headers=kid).json()
    assert [(t["name"], t["icon"]) for t in tags] == [("Garten", None), ("Velo", "🚲")]


def test_name_rules(client):
    admin = admin_headers(client)
    assert add(client, admin, "").status_code == 422
    assert add(client, admin, "x" * 51).status_code == 422
    add(client, admin, "Velo")
    response = add(client, admin, "velo")
    assert response.status_code == 400 and response.json()["detail"] == "A tag with that name already exists"


def test_duplicate_in_german(client):
    admin = admin_headers(client)
    set_language(admin, "de")
    add(client, admin, "Velo")
    assert add(client, admin, "VELO").json()["detail"] == "Einen Tag mit diesem Namen gibt es schon"


def test_only_parents_manage_tags(client):
    kid = register(client, "kid", role="CHILD")
    response = add(client, kid, "Velo")
    assert response.status_code == 403 and response.json()["detail"] == "Only parents can manage tags"


def test_rename(client):
    admin = admin_headers(client)
    tag = add(client, admin, "Velo").json()
    add(client, admin, "Garten")
    assert client.put(f"{TAGS}/{tag['id']}", json={"name": "Fahrrad"}, headers=admin).json()["name"] == "Fahrrad"
    assert client.put(f"{TAGS}/{tag['id']}", json={"name": "garten"}, headers=admin).status_code == 400


def item_with_tags(client, headers, tag_ids):
    account = create_account(client, headers)
    with database.SessionLocal() as db:
        clothing = db.query(models.Category).filter(models.Category.name == "Clothing").one()
        transaction = models.Transaction(
            account_id=account, category_id=clothing.id, amount=-80, date=datetime(2026, 10, 1)
        )
        tags = db.query(models.Tag).filter(models.Tag.id.in_(tag_ids)).all()
        transaction.items = [
            models.TransactionItem(position=0, name="Hose", amount=80, category_id=clothing.id, tags=tags)
        ]
        db.add(transaction)
        db.commit()


def test_delete_removes_the_tag_from_items(client):
    admin = admin_headers(client)
    velo, sport = add(client, admin, "Velo").json(), add(client, admin, "Sport").json()
    item_with_tags(client, admin, [velo["id"], sport["id"]])
    assert client.get(f"{TAGS}/usage", headers=admin).json()[velo["id"]] == {
        "items": 1,
        "budgets": 0,
        "assets": 0,
        "article_rules": 0,
    }
    assert client.delete(f"{TAGS}/{velo['id']}", headers=admin).status_code == 200
    with database.SessionLocal() as db:
        item = db.query(models.TransactionItem).one()
        assert [t.name for t in item.tags] == ["Sport"]


def test_tag_used_by_a_budget_cannot_be_deleted(client):
    admin = admin_headers(client)
    velo = add(client, admin, "Velo").json()
    with database.SessionLocal() as db:
        owner = db.query(models.User).filter(models.User.username == "Admin").one()
        db.add(models.Budget(user_id=owner.id, tag_id=velo["id"], limit=4000, period="YEARLY"))
        db.commit()
    response = client.delete(f"{TAGS}/{velo['id']}", headers=admin)
    assert (
        response.status_code == 409 and response.json()["detail"] == "A budget uses this tag; delete the budget first"
    )


def test_usage_counts_investments(client):
    # Settings warns before deleting a tag an investment uses
    mum = register(client, "mum")
    velo = add(client, mum, "Velo").json()
    body = {"name": "Velo", "price": 1200, "purchase_date": "2025-04-01", "lifespan_years": 8}
    body |= {"owner_id": user_id(client, mum, "mum"), "tag_ids": [velo["id"]]}
    assert client.post(f"{BASE_URL}/assets", json=body, headers=mum).status_code == 200
    assert client.get(f"{TAGS}/usage", headers=mum).json()[velo["id"]] == {
        "items": 0,
        "budgets": 0,
        "assets": 1,
        "article_rules": 0,
    }
