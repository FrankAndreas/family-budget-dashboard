import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway database before it is imported, so tests never touch data/budget.db
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database, models  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_categories  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts with empty tables and the default categories."""
    models.Base.metadata.drop_all(bind=database.engine)
    models.Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        seed_categories(db)
    yield


@pytest.fixture
def client():
    return TestClient(app)
