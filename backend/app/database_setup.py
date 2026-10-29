"""Bring the database to the current schema on start-up, with the Alembic migrations in app/migrations.

A database made before migrations existed (no alembic_version table) first gets the columns added before then;
the baseline migration creates only missing tables, so such a database upgrades like an empty one.
"""

import logging
from importlib.resources import files

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

HEAD = "0021"

# Columns added before migrations existed; an old database may lack them (only used to catch it up)
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


def alembic_config(engine: Engine) -> Config:
    config = Config()
    config.set_main_option("script_location", str(files("app") / "migrations"))
    return config


def run(engine: Engine, action, *args) -> None:
    """Run an Alembic command. SQLite: with link checking off, so migrations can rebuild tables that others point to
    (it can't be switched inside a transaction, so before it starts); log_broken_links checks afterwards."""
    config = alembic_config(engine)
    sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as connection:
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        try:
            with connection.begin():
                config.attributes["connection"] = connection
                action(config, *args)
        finally:
            if sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


def catch_up(engine: Engine) -> None:
    """Add the columns an old database's existing tables may lack; the baseline migration adds missing tables."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in NEW_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def log_broken_links(engine: Engine) -> None:
    """Rows whose links point nowhere (left by versions before the links were enforced); the app runs anyway."""
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA foreign_key_check").all()
    counts: dict[str, int] = {}
    for table, *_ in rows:
        counts[table] = counts.get(table, 0) + 1
    for table, count in sorted(counts.items()):
        logger.warning("Broken links in the database: %s: %d row%s", table, count, "" if count == 1 else "s")


def setup(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    if tables and "alembic_version" not in tables:
        # Made before migrations: bring its tables to the baseline, then the baseline migration adds missing ones
        catch_up(engine)
    run(engine, command.upgrade, "head")
    if engine.dialect.name == "sqlite":
        log_broken_links(engine)
