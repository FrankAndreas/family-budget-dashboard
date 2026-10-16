"""Alembic environment. The app runs the migrations itself on start-up (app/database_setup.py) and passes its
connection; `alembic` on the command line (backend/alembic.ini) uses DATABASE_URL like the app."""

from alembic import context
from sqlalchemy import create_engine

from app import database, models

config = context.config
target_metadata = models.Base.metadata


def run(connection) -> None:
    # Batch mode: SQLite can't alter most things in place, Alembic rebuilds the table instead
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    engine = create_engine(database.SQLALCHEMY_DATABASE_URL)
    database.enable_foreign_keys(engine)
    with engine.connect() as conn:
        run(conn)
