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
from app.money import Money
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
            # Converted to cents by 0004
            assert conn.execute(text("SELECT amount FROM transactions")).scalar() == -500
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


class TestMoney:
    def test_round_trip(self):
        kind = Money()
        for francs, cents in [(84.3, 8430), (0.1, 10), (-22.1, -2210), (1234.56, 123456), (None, None)]:
            assert kind.process_bind_param(francs, None) == cents
            assert kind.process_result_value(cents, None) == francs

    def test_exact_sums(self, client):
        headers = register(client, "mum")
        account = create_account(client, headers)
        for amount in (0.1, 0.2):
            add_transaction(client, headers, account, category_id(client, "Gift"), amount)
        assert balance(client, headers, account) == 0.3
        with database.engine.connect() as conn:
            assert sorted(conn.execute(text("SELECT amount FROM transactions")).scalars()) == [10, 20]

    def test_query_literal_in_cents(self, client):
        headers = register(client, "mum")
        account = create_account(client, headers)
        add_transaction(client, headers, account, category_id(client, "Groceries"), 5)
        with database.SessionLocal() as db:
            assert db.query(models.Transaction).filter(models.Transaction.amount < -4.99).count() == 1
            assert db.query(models.Transaction).filter(models.Transaction.amount < -5.01).count() == 0


class TestCentsMigration:
    def at_0003_with_floats(self, tmp_path):
        engine = sqlite(tmp_path)
        database_setup.setup(engine)
        database_setup.run(engine, command.downgrade, "0003")
        without_link_checks(
            engine,
            "INSERT INTO users (id, username, role, is_active, has_allowance) VALUES ('u1', 'mum', 'PARENT', 1, 1)",
            "INSERT INTO accounts (id, user_id, name, balance) VALUES ('a1', 'u1', 'Bank', 0)",
            "INSERT INTO transactions (id, account_id, amount) VALUES ('t1', 'a1', 84.3), ('t2', 'a1', -22.10), "
            "('t3', 'a1', 0.30000000000000004)",
            "INSERT INTO settlements (id, from_user_id, to_user_id, amount, from_transaction_id, to_transaction_id) "
            "VALUES ('s1', 'u1', 'u1', 84.3, 't1', 't2')",
            "INSERT INTO wishes (id, name, owner_id, estimate, best_price, position) "
            "VALUES ('w1', 'Bike', 'u1', NULL, 99.95, 1)",
        )
        return engine

    def test_upgrade_converts_to_cents(self, tmp_path):
        engine = self.at_0003_with_floats(tmp_path)
        database_setup.setup(engine)
        with engine.connect() as conn:
            amounts = dict(conn.execute(text("SELECT id, amount FROM transactions")).all())
            assert amounts == {"t1": 8430, "t2": -2210, "t3": 30}
            assert conn.execute(text("SELECT amount FROM settlements")).scalar() == 8430
            assert tuple(conn.execute(text("SELECT estimate, best_price FROM wishes")).one()) == (None, 9995)
            assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert "balance" not in {c["name"] for c in inspect(engine).get_columns("accounts")}
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), models.Base.metadata)
        assert diff == []

    def test_downgrade_restores_francs_and_balance(self, tmp_path):
        engine = self.at_0003_with_floats(tmp_path)
        database_setup.setup(engine)
        database_setup.run(engine, command.downgrade, "0003")
        with engine.connect() as conn:
            assert dict(conn.execute(text("SELECT id, amount FROM transactions")).all()) == {
                "t1": 84.3,
                "t2": -22.1,
                "t3": 0.3,
            }
            assert conn.execute(text("SELECT balance FROM accounts")).scalar() == 62.5


def test_sqlite_folder_is_created(tmp_path):
    database.ensure_sqlite_folder(f"sqlite:///{tmp_path}/new/folder/budget.db")
    assert (tmp_path / "new" / "folder").is_dir()
    database.ensure_sqlite_folder("sqlite://")  # in memory: nothing to create
    database.ensure_sqlite_folder("postgresql://host/db")  # not SQLite: nothing to do


def test_category_keys_migration(tmp_path):
    engine = sqlite(tmp_path)
    database_setup.setup(engine)
    database_setup.run(engine, command.downgrade, "0005")
    without_link_checks(
        engine,
        "INSERT INTO categories (id, name, type) VALUES ('c1', 'Settle up', 'TRANSFER'), ('c2', 'Groceries', 'EXPENSE')",
    )
    database_setup.setup(engine)
    with engine.connect() as conn:
        keys = dict(conn.execute(text("SELECT name, system_key FROM categories")).all())
    assert keys == {"Settle up": "SETTLE_UP", "Groceries": None}
