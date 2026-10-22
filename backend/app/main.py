import logging
import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from . import (
    database,
    database_setup,
    api,
    common_api,
    export_api,
    import_api,
    month_check,
    wishes_api,
    import_rules,
    reports,
    categories_api,
    tags_api,
    i18n,
)
from .seed import seed_admin, seed_categories

# Create or upgrade the schema (Alembic migrations in app/migrations)
database_setup.setup(database.engine)

logger = logging.getLogger(__name__)

# Make sure a fresh database has categories (transactions need one) and a first parent to log in with
with database.SessionLocal() as db:
    seed_categories(db)
    initial_pin = seed_admin(db)
if initial_pin:
    logger.warning(
        "Created the first parent 'Admin' with INITIAL PIN %s. Log in and change it in Settings > Family.", initial_pin
    )

app = FastAPI(
    title="Family Budget Dashboard API",
    description="Backend for the Family Budget Dashboard",
    version="0.1.0",
    # Every request starts in the browser's language; a checked login switches to the person's own
    dependencies=[Depends(i18n.language_from_header)],
)

app.include_router(api.router, prefix="/api/v1")
app.include_router(common_api.router, prefix="/api/v1")
app.include_router(export_api.router, prefix="/api/v1")
app.include_router(import_api.router, prefix="/api/v1")
app.include_router(month_check.router, prefix="/api/v1")
app.include_router(wishes_api.router, prefix="/api/v1")
app.include_router(import_rules.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(categories_api.router, prefix="/api/v1")
app.include_router(tags_api.router, prefix="/api/v1")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    # Comma-separated; the browser tests run the frontend on their own port (e2e/playwright.config.ts)
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency removed from here, imported from database


@app.get("/")
async def root():
    return {"message": "Welcome to the Family Budget Dashboard API"}


@app.get("/health")
async def health_check(db: Session = Depends(database.get_db)):
    return {"status": "ok", "db": "connected"}
