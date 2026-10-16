import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/budget.db")


def ensure_sqlite_folder(url: str) -> None:
    """SQLite creates the database file but not its folder (e.g. backend/data in a fresh clone)."""
    database = make_url(url).database if url.startswith("sqlite") else None
    if database and database != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(database)), exist_ok=True)


ensure_sqlite_folder(SQLALCHEMY_DATABASE_URL)

# check_same_thread is needed for SQLite
connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)


def enable_foreign_keys(engine: Engine) -> None:
    """SQLite only checks the declared links (FOREIGN KEY ... REFERENCES) when asked to, per connection."""
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _enforce(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


enable_foreign_keys(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
