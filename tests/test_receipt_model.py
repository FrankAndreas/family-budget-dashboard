"""Tables for receipt items, tags and attachments (issue #56): what goes when a booking, account or person goes."""

from datetime import datetime

from helpers import add_member, BASE_URL, admin_headers, create_account, register, user_id

from app import database, models


def category(db, name):
    return db.query(models.Category).filter(models.Category.name == name).one()


def itemized_booking(account_id, person_id=None):
    """A booking with two items (one with two tags) and one attachment row; returns its id."""
    with database.SessionLocal() as db:
        velo, sport = models.Tag(name="Velo"), models.Tag(name="Sport")
        transaction = models.Transaction(
            account_id=account_id, category_id=category(db, "Clothing").id, amount=-83.40, date=datetime(2026, 10, 1)
        )
        transaction.items = [
            models.TransactionItem(position=0, name="Brot", amount=3.50, category_id=category(db, "Groceries").id),
            models.TransactionItem(
                position=1,
                name="Velo-Hose",
                amount=79.90,
                category_id=category(db, "Clothing").id,
                person_id=person_id,
                tags=[velo, sport],
            ),
        ]
        owner = db.query(models.Account).filter(models.Account.id == account_id).one().user_id
        transaction.attachments = [
            models.Attachment(owner_id=owner, filename="beleg.jpg", content_type="image/jpeg", size=3, sha256="x")
        ]
        db.add(transaction)
        db.commit()
        return transaction.id


def counts():
    with database.SessionLocal() as db:
        return (
            db.query(models.TransactionItem).count(),
            db.query(models.TransactionItemTag).count(),
            db.query(models.Attachment).count(),
            db.query(models.Tag).count(),
        )


def test_deleting_a_booking_deletes_its_items_tags_and_attachment_rows(client):
    mum = register(client, "mum")
    transaction_id = itemized_booking(create_account(client, mum))
    assert counts() == (2, 2, 1, 2)
    assert client.delete(f"{BASE_URL}/transactions/{transaction_id}", headers=mum).status_code == 200
    # The tags themselves stay
    assert counts() == (0, 0, 0, 2)


def test_deleting_an_account_with_itemized_bookings(client):
    mum = register(client, "mum")
    account = create_account(client, mum)
    itemized_booking(account)
    assert client.delete(f"{BASE_URL}/accounts/{account}", headers=mum).status_code == 200
    assert counts()[:3] == (0, 0, 0)


def test_removing_a_person_clears_their_items(client):
    admin = admin_headers(client)
    add_member(client, "kid")
    kid = user_id(client, admin, "kid")
    itemized_booking(create_account(client, admin), person_id=kid)
    assert client.request("DELETE", f"{BASE_URL}/users/{kid}", json={"items": []}, headers=admin).status_code == 200
    with database.SessionLocal() as db:
        items = db.query(models.TransactionItem).all()
        assert len(items) == 2 and all(item.person_id is None for item in items)
