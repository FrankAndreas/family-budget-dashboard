"""Bulk import of transactions from a CSV or JSON file written by an external tool."""

from sqlalchemy import create_engine, inspect, text

from helpers import BASE_URL, add_transaction, category_id, create_account, register


class TestReference:
    def test_transaction_keeps_reference(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        t = add_transaction(client, headers, account, category_id(client, "Groceries"), 5, reference="r1").json()
        assert t["reference"] == "r1"
        assert add_transaction(client, headers, account, category_id(client, "Groceries"), 5).json()["reference"] is None

    def test_reference_length_limited(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        response = add_transaction(client, headers, account, category_id(client, "Groceries"), 5, reference="x" * 201)
        assert response.status_code == 422

    def test_migration_adds_reference(self, tmp_path):
        from app.migrate import add_missing_columns

        engine = create_engine(f"sqlite:///{tmp_path}/old.db")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users (id VARCHAR PRIMARY KEY, has_allowance BOOLEAN)"))
            conn.execute(text("CREATE TABLE transactions (id VARCHAR PRIMARY KEY, amount FLOAT)"))
        add_missing_columns(engine)
        assert "reference" in {c["name"] for c in inspect(engine).get_columns("transactions")}
