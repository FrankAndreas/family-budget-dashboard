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

from app import auth, database, models  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_categories  # noqa: E402
from helpers import ADMIN, ADMIN_PIN  # noqa: E402

# Cheap PIN hashes: at bcrypt's default cost, hashing took about 95% of the suite's time.
# Verifying reads the cost from the hash, so logins in the tests are cheap too.
auth.PIN_HASH_ROUNDS = 4


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts with the default categories and one parent ("Admin", like a fresh install)."""
    models.Base.metadata.drop_all(bind=database.engine)
    models.Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        seed_categories(db)
        # Known PIN instead of the random one a real install gets
        db.add(models.User(username=ADMIN, pin_hash=auth.get_pin_hash(ADMIN_PIN), role=models.UserRole.PARENT))
        db.commit()
    yield


@pytest.fixture(autouse=True)
def attachments_dir(tmp_path, monkeypatch):
    """Receipt files go to a folder of their own per test (issue #56)."""
    folder = tmp_path / "attachments"
    monkeypatch.setenv("ATTACHMENTS_DIR", str(folder))
    return folder


@pytest.fixture
def client():
    return TestClient(app)
