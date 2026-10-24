"""The backend's own start-up lines reach the container log (docker logs), not only uvicorn's (issue #57)."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"


def start(tmp_path, **env):
    """Import the app in a fresh Python, as uvicorn does when the container starts; return what it printed."""
    environment = {
        **{k: v for k, v in os.environ.items() if k != "INBOUND_SECRET"},
        "DATABASE_URL": f"sqlite:///{tmp_path}/budget.db",
        "ATTACHMENTS_DIR": str(tmp_path / "attachments"),
        "INITIAL_ADMIN_PIN": "1111",
        **env,
    }
    done = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout + done.stderr


def test_receipt_mails_configured_is_logged(tmp_path):
    output = start(tmp_path, INBOUND_SECRET="test-secret")
    assert "Receipt mails: configured" in output
    assert "test-secret" not in output


def test_receipt_mails_off_is_logged(tmp_path):
    assert "Receipt mails: not configured (INBOUND_SECRET empty)" in start(tmp_path)
