"""Wrong PINs: 5 in a row lock the username for 15 minutes (issue #31)."""

from datetime import datetime, timedelta

import pytest

from app import auth
from helpers import BASE_URL, admin_headers, register, user_id


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 16, 12, 0)

    def __call__(self):
        return self.value


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(auth, "now", fake)
    return fake


def attempt(client, pin, username="mum"):
    return client.post(f"{BASE_URL}/login", json={"username": username, "pin": pin})


def wrong(client, times, username="mum"):
    for _ in range(times):
        assert attempt(client, "9999", username).status_code == 401


def test_five_wrong_pins_lock_the_username(client, clock):
    register(client, "mum")
    wrong(client, 5)
    locked = attempt(client, "1234")
    assert locked.status_code == 429
    assert locked.json()["detail"] == "Too many wrong PINs. Try again in 15 minutes."
    clock.value += timedelta(minutes=14, seconds=1)
    assert attempt(client, "1234").json()["detail"] == "Too many wrong PINs. Try again in 1 minute."
    clock.value += timedelta(minutes=1)
    assert attempt(client, "1234").status_code == 200


def test_correct_pin_resets_the_count(client, clock):
    register(client, "mum")
    wrong(client, 4)
    assert attempt(client, "1234").status_code == 200
    wrong(client, 4)
    assert attempt(client, "1234").status_code == 200


def test_after_the_lock_a_new_count_starts(client, clock):
    register(client, "mum")
    wrong(client, 5)
    clock.value += timedelta(minutes=15)
    wrong(client, 4)
    assert attempt(client, "1234").status_code == 200


def test_other_users_are_not_affected(client, clock):
    register(client, "mum")
    register(client, "dad")
    wrong(client, 5)
    assert attempt(client, "1234", "dad").status_code == 200


def test_unknown_usernames_are_not_counted(client, clock):
    for _ in range(10):
        assert attempt(client, "1234", "nobody").status_code == 401


def test_new_pin_from_a_parent_unlocks(client, clock):
    register(client, "kid", role="CHILD")
    wrong(client, 5, "kid")
    admin = admin_headers(client)
    changed = client.put(f"{BASE_URL}/users/{user_id(client, admin, 'kid')}", json={"pin": "4321"}, headers=admin)
    assert changed.status_code == 200
    assert attempt(client, "4321", "kid").status_code == 200


def test_lockout_is_logged(client, clock, caplog):
    register(client, "mum")
    with caplog.at_level("WARNING"):
        wrong(client, 5)
    assert "Login for 'mum' locked for 15 minutes after 5 wrong PINs" in caplog.text
