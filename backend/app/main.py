import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

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
    rule_presets,
    reconcile,
    reports,
    categories_api,
    tags_api,
    attachments,
    receipt_ai,
    emails_api,
    inbox,
    scans,
    i18n,
)
from .seed import seed_admin

# The app's own lines (start-up status, receipt mails, AI errors) go to the container log next to uvicorn's;
# without a handler Python would only print warnings
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
logging.getLogger("app").addHandler(_handler)
logging.getLogger("app").setLevel(logging.INFO)

# Create or upgrade the schema (Alembic migrations in app/migrations)
database_setup.setup(database.engine)

logger = logging.getLogger(__name__)

# Make sure a fresh database has categories (transactions need one) and a first parent to log in with;
# receipts read but never booked are removed after a day (issue #56), unreleased receipt mails after 30 (#57)
with database.SessionLocal() as db:
    rule_presets.seed_new_database(db)
    initial_pin = seed_admin(db)
    attachments.sweep(db)
    inbox.sweep(db)
    # Scanned receipts whose reading a restart cut off are read again
    scans.resume(db)
logger.info(
    "Receipt mails: %s", "configured" if os.getenv("INBOUND_SECRET") else "not configured (INBOUND_SECRET empty)"
)
if initial_pin:
    logger.warning(
        "Created the first parent 'Admin' with INITIAL PIN %s. Log in and change it in Settings > Family.", initial_pin
    )


async def sweep_daily() -> None:
    while True:
        await asyncio.sleep(24 * 60 * 60)
        with database.SessionLocal() as session:
            attachments.sweep(session)
            inbox.sweep(session)


async def read_scans_regularly() -> None:
    """Scanned receipts still waiting (e.g. over the hourly AI limit) are read now and every 15 minutes."""
    while True:
        await asyncio.to_thread(scans.read_waiting)
        await asyncio.sleep(15 * 60)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    tasks = [asyncio.create_task(sweep_daily()), asyncio.create_task(read_scans_regularly())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(
    lifespan=lifespan,
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
app.include_router(rule_presets.router, prefix="/api/v1")
app.include_router(reconcile.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(categories_api.router, prefix="/api/v1")
app.include_router(tags_api.router, prefix="/api/v1")
app.include_router(attachments.router, prefix="/api/v1")
app.include_router(receipt_ai.router, prefix="/api/v1")
app.include_router(emails_api.router, prefix="/api/v1")
app.include_router(inbox.router, prefix="/api/v1")
app.include_router(scans.router, prefix="/api/v1")

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
