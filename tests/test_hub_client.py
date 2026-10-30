"""The family hub's answers as the app reads them (spec 2026-10-30, part B): a stub hub on a local port."""

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import hub

TOKEN = "tok-secret-value"
LENA = {"id": 7, "name": "Lena", "role": "CHILD", "color": "#f59e0b", "language": "en"}


class Stub:
    """What the stub hub answers, and the requests it saw."""

    def __init__(self):
        self.session = {"valid": True, "person": {**LENA, "email": "lena@example.ch"}, "access": True}
        self.people = [LENA]
        self.people_status = 200
        self.requests: list[tuple[str, str | None]] = []


@pytest.fixture
def family_hub():
    """The real client here, not the fake hub conftest installs for every other test."""


@pytest.fixture
def stub(monkeypatch):
    found = Stub()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            found.requests.append((self.path, self.headers.get("Authorization")))
            if self.path.startswith("/api/session"):
                status, body = 200, found.session
            elif self.path == "/api/apps/budget/people":
                status, body = found.people_status, found.people
            else:
                status, body = 404, {"detail": "not found"}
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("HUB_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.delenv("HUB_APP_KEY", raising=False)
    hub.forget()
    yield found
    server.shutdown()
    hub.forget()


def test_session_valid_with_access(stub):
    person, access = hub.fetch_session(TOKEN)
    assert person == hub.HubPerson(id=7, name="Lena", role="CHILD", color="#f59e0b", language="en")
    assert access is True
    assert stub.requests == [("/api/session?app=budget", f"Bearer {TOKEN}")]


def test_session_without_access(stub):
    stub.session["access"] = False
    person, access = hub.fetch_session(TOKEN)
    assert person is not None and access is False


def test_session_invalid(stub):
    stub.session = {"valid": False, "person": None}
    assert hub.fetch_session(TOKEN) == (None, False)


def test_session_cached(stub):
    hub.session(TOKEN)
    hub.session(TOKEN)
    assert len(stub.requests) == 1
    hub.forget()
    hub.session(TOKEN)
    assert len(stub.requests) == 2


def test_hub_down_raises(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("HUB_URL", f"http://127.0.0.1:{port}")
    hub.forget()
    with pytest.raises(hub.HubUnavailable):
        hub.session(TOKEN)
    with pytest.raises(hub.HubUnavailable):
        hub.fetch_people(TOKEN)


def test_people_parsed(stub):
    assert hub.fetch_people(TOKEN) == [hub.HubPerson(**LENA)]
    assert stub.requests[-1] == ("/api/apps/budget/people", f"Bearer {TOKEN}")


def test_people_forbidden_is_empty(stub):
    stub.people_status = 403
    assert hub.fetch_people(TOKEN) == []


def test_token_not_logged(stub, caplog):
    caplog.set_level(logging.DEBUG)
    hub.session(TOKEN)
    hub.fetch_people(TOKEN)
    stub.people_status = 500
    with pytest.raises(hub.HubUnavailable):
        hub.fetch_people(TOKEN)
    assert TOKEN not in caplog.text


def test_settings(monkeypatch):
    monkeypatch.setenv("HUB_URL", "http://hub:8086/")
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://home.local.example.ch/")
    monkeypatch.setenv("HUB_APP_KEY", "money")
    assert (hub.hub_url(), hub.public_url(), hub.app_key()) == (
        "http://hub:8086",
        "https://home.local.example.ch",
        "money",
    )


def test_empty_settings_count_as_unset(monkeypatch):
    # docker-compose passes HUB_URL=${HUB_URL:-}: an empty value, never a login address of "" (the app would send the
    # browser to itself, again and again)
    for name in ("HUB_URL", "HUB_PUBLIC_URL", "HUB_APP_KEY"):
        monkeypatch.setenv(name, "")
    assert (hub.hub_url(), hub.public_url(), hub.app_key()) == (
        "http://localhost:8086",
        "http://localhost:8086",
        "budget",
    )


def test_no_access_not_kept(stub):
    # Someone given access a moment ago gets in at once; only a valid login with access is kept for a minute
    stub.session["access"] = False
    assert hub.session(TOKEN)[1] is False
    stub.session["access"] = True
    assert hub.session(TOKEN)[1] is True
    stub.session = {"valid": False, "person": None}
    assert hub.session("tok-other") == (None, False)
    assert len(stub.requests) == 3
