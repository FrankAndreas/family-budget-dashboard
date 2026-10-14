from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# create_all() only creates missing tables, not missing columns. Columns added after the
# first release are listed here and added to existing databases on startup.
NEW_COLUMNS = {
    "users": {"has_allowance": "BOOLEAN NOT NULL DEFAULT 1"},
    "transactions": {
        "member_id": "VARCHAR REFERENCES users(id)",
        "split_id": "VARCHAR REFERENCES splits(id)",
        "split_shares": "JSON",
        "asset_id": "VARCHAR REFERENCES assets(id)",
        "reference": "VARCHAR",
    },
}


def add_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in NEW_COLUMNS.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
