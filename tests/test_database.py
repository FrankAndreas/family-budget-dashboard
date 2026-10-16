"""Database foundation: enforced links, calculated balances, migrations on start-up (issue #29)."""

import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app import database, database_setup, models
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


def sqlite(tmp_path: Path, name: str = "app.db"):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    database.enable_foreign_keys(engine)
    return engine


def without_link_checks(engine, *statements):
    """Write rows that break links, as an older version without enforcement could have left them."""
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        for statement in statements:
            conn.exec_driver_sql(statement)
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


class TestMigrations:
    def test_empty_database_matches_the_models(self, tmp_path):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), models.Base.metadata)
        assert diff == []

    def test_start_up_twice(self, tmp_path):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        database_setup.setup(engine)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == database_setup.HEAD

    def test_old_database_is_caught_up(self, tmp_path):
        engine = sqlite(tmp_path)
        # As an early version made it: no alembic_version, a column and most tables missing
        without_link_checks(
            engine,
            "CREATE TABLE users (id VARCHAR PRIMARY KEY, username VARCHAR, pin_hash VARCHAR, role VARCHAR(6), "
            "privacy_enabled BOOLEAN, is_active BOOLEAN, settings JSON)",
            "INSERT INTO users (id, username, role, is_active) VALUES ('u1', 'mum', 'PARENT', 1)",
            "CREATE TABLE transactions (id VARCHAR PRIMARY KEY, account_id VARCHAR, category_id VARCHAR, "
            "amount FLOAT, date DATETIME, description VARCHAR)",
            "INSERT INTO transactions (id, amount) VALUES ('t1', -5)",
        )
        database_setup.setup(engine)
        tables = set(inspect(engine).get_table_names())
        assert {"accounts", "transactions", "wishes", "import_rules", "alembic_version"} <= tables
        assert "has_allowance" in {c["name"] for c in inspect(engine).get_columns("users")}
        assert "reference" in {c["name"] for c in inspect(engine).get_columns("transactions")}
        with engine.connect() as conn:
            assert conn.execute(text("SELECT username FROM users")).scalar() == "mum"
            assert conn.execute(text("SELECT amount FROM transactions")).scalar() == -5
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == database_setup.HEAD

    def test_repair_clears_broken_optional_links(self, tmp_path):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        database_setup.run(engine, command.downgrade, "0001")
        without_link_checks(
            engine,
            "INSERT INTO users (id, username, role, is_active, has_allowance) VALUES ('u1', 'mum', 'PARENT', 1, 1)",
            "INSERT INTO accounts (id, user_id, name) VALUES ('a1', 'u1', 'Bank')",
            "INSERT INTO transactions (id, account_id, amount, member_id, split_id, asset_id) "
            "VALUES ('t1', 'a1', -5, 'gone', 'gone', 'gone')",
            "INSERT INTO transactions (id, account_id, amount, member_id) VALUES ('t2', 'a1', -5, 'u1')",
        )
        database_setup.setup(engine)
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, member_id, split_id, asset_id, account_id FROM transactions")).all()
        assert sorted(tuple(r) for r in rows) == [("t1", None, None, None, "a1"), ("t2", "u1", None, None, "a1")]

    def test_start_up_logs_broken_links(self, tmp_path, caplog):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        without_link_checks(engine, "INSERT INTO budgets (id, user_id) VALUES ('b1', 'gone')")
        with caplog.at_level(logging.WARNING):
            database_setup.setup(engine)
        assert "budgets: 1 row" in caplog.text
