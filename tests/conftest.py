import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway database before it is imported, so tests never touch data/budget.db
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
# The existing tests check English texts and English default categories; German tests set "de" themselves
os.environ["DEFAULT_LANGUAGE"] = "en"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import fake_hub  # noqa: E402
from app import database, hub, models  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_categories  # noqa: E402
from helpers import ADMIN  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts with the default categories and one parent "Admin": a row from before the family hub
    (no hub id), which the first login links to the hub's Admin by name."""
    models.Base.metadata.drop_all(bind=database.engine)
    models.Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        seed_categories(db)
        db.add(models.User(username=ADMIN, role=models.UserRole.PARENT))
        db.commit()
    yield


@pytest.fixture(autouse=True)
def family_hub(monkeypatch):
    """A fake family hub instead of the real one (tests/fake_hub.py), with the parent Admin."""
    fake = fake_hub.FakeHub()
    monkeypatch.setattr(fake_hub, "current", fake)
    monkeypatch.setattr(hub, "fetch_session", fake.fetch_session)
    monkeypatch.setattr(hub, "fetch_people", fake.fetch_people)
    fake.add(ADMIN, "PARENT")
    yield fake
    hub.forget()


@pytest.fixture(autouse=True)
def attachments_dir(tmp_path, monkeypatch):
    """Receipt files go to a folder of their own per test (issue #56)."""
    folder = tmp_path / "attachments"
    monkeypatch.setenv("ATTACHMENTS_DIR", str(folder))
    return folder


@pytest.fixture
def client():
    return TestClient(app)
