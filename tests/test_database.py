"""Database foundation: enforced links, calculated balances, migrations on start-up (issue #29)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import database
from helpers import BASE_URL, add_transaction, balance, category_id, create_account, register


class TestForeignKeys:
    def test_enforced(self):
        with database.engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            with pytest.raises(IntegrityError):
                conn.execute(
                    text("INSERT INTO transactions (id, account_id, amount) VALUES ('t1', 'no-such-account', 1)")
                )


class TestBalances:
    def test_sum_of_transactions(self, client):
        headers = register(client, "mum")
        account = create_account(client, headers)
        assert balance(client, headers, account) == 0
        gift, groceries = category_id(client, "Gift"), category_id(client, "Groceries")
        first = add_transaction(client, headers, account, gift, 0.1).json()
        add_transaction(client, headers, account, gift, 0.2)
        assert balance(client, headers, account) == 0.3
        client.put(
            f"{BASE_URL}/transactions/{first['id']}", json={"amount": 10, "category_id": groceries}, headers=headers
        )
        assert balance(client, headers, account) == -9.8
        client.delete(f"{BASE_URL}/transactions/{first['id']}", headers=headers)
        assert balance(client, headers, account) == 0.2

    def test_stored_column_is_not_used(self, client):
        headers = register(client, "mum")
        account = create_account(client, headers)
        add_transaction(client, headers, account, category_id(client, "Gift"), 5)
        with database.engine.begin() as conn:
            conn.execute(text("UPDATE accounts SET balance = 999"))
        assert balance(client, headers, account) == 5
