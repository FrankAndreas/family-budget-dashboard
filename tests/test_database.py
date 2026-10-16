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
