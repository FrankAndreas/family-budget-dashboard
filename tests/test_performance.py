"""Performance review 2026-11-08: the analysis export doesn't ask the database once per booking, and the Common tab
gets only the newest shared expenses."""

from contextlib import contextmanager

from sqlalchemy import event

from app import database
from helpers import BASE_URL, admin_headers, category_id, create_account, create_split, register, user_id


@contextmanager
def statements():
    counted = [0]

    def count(*_args):
        counted[0] += 1

    event.listen(database.engine, "before_cursor_execute", count)
    try:
        yield counted
    finally:
        event.remove(database.engine, "before_cursor_execute", count)


def add_receipts(client, headers, account, tag, count):
    for n in range(count):
        item = {"name": f"Brot {n}", "amount": 3.5, "category_id": category_id(client, "Groceries"), "tag_ids": [tag]}
        receipt = {"account_id": account, "items": [item, {**item, "name": f"Milch {n}"}]}
        assert client.post(f"{BASE_URL}/transactions", json=receipt, headers=headers).status_code == 200


def export_statements(client, headers) -> int:
    with statements() as counted:
        assert client.get(f"{BASE_URL}/export/analysis.zip", headers=headers).status_code == 200
    return counted[0]


def test_export_queries_dont_grow_with_bookings(client):
    tag = client.post(f"{BASE_URL}/tags", json={"name": "Velo"}, headers=admin_headers(client)).json()["id"]
    mum = register(client, "mum")
    account = create_account(client, mum)
    add_receipts(client, mum, account, tag, 3)
    few = export_statements(client, mum)
    add_receipts(client, mum, account, tag, 20)
    assert export_statements(client, mum) == few


def test_common_tab_gets_the_newest_shared_expenses(client):
    mum = register(client, "mum")
    register(client, "dad")
    ids = [user_id(client, mum, name) for name in ("mum", "dad", "Admin")]
    split = create_split(client, mum, "Halb", dict(zip(ids, (50, 50, 0)))).json()["id"]
    account = create_account(client, mum)
    for day in range(1, 6):
        booking = {
            "account_id": account,
            "category_id": category_id(client, "Groceries"),
            "amount": 10 * day,
            "description": f"Einkauf {day}",
            "split_id": split,
            "date": f"2026-10-0{day}T12:00:00Z",
        }
        assert client.post(f"{BASE_URL}/transactions", json=booking, headers=mum).status_code == 200
    newest = client.get(f"{BASE_URL}/common/expenses", params={"limit": 2}, headers=mum).json()
    assert [e["description"] for e in newest] == ["Einkauf 5", "Einkauf 4"]
    assert len(client.get(f"{BASE_URL}/common/expenses", headers=mum).json()) == 5
    # The balance still counts every one of them
    balance = {b["user_id"]: b["amount"] for b in client.get(f"{BASE_URL}/common/balance", headers=mum).json()}
    assert balance[ids[1]] == -75.0
