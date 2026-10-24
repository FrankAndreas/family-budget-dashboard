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


# Repeated lockouts (issue #86): each one in a row doubles the lock, up to a day, so guessing a 4-digit PIN takes
# years instead of days; the person sees the wrong PINs after their next login


def lock_out(client, clock, username="mum"):
    """Five wrong PINs, then the lock's message; the clock moves past the lock."""
    wrong(client, 5, username)
    detail = attempt(client, "1234", username).json()["detail"]
    user = locked_user(username)
    clock.value = user.locked_until
    return detail


def locked_user(username):
    from app import database, models

    with database.SessionLocal() as db:
        return db.query(models.User).filter(models.User.username == username).one()


def test_each_lockout_in_a_row_doubles_the_lock(client, clock):
    register(client, "mum")
    assert lock_out(client, clock) == "Too many wrong PINs. Try again in 15 minutes."
    assert lock_out(client, clock) == "Too many wrong PINs. Try again in 30 minutes."
    assert lock_out(client, clock) == "Too many wrong PINs. Try again in 1 hour."
    assert lock_out(client, clock) == "Too many wrong PINs. Try again in 2 hours."


def test_the_lock_is_at_most_a_day(client, clock):
    register(client, "mum")
    for _ in range(9):
        detail = lock_out(client, clock)
    assert detail == "Too many wrong PINs. Try again in 24 hours."


def test_a_correct_login_starts_again_at_15_minutes(client, clock):
    register(client, "mum")
    lock_out(client, clock)
    lock_out(client, clock)
    assert attempt(client, "1234").status_code == 200
    assert lock_out(client, clock) == "Too many wrong PINs. Try again in 15 minutes."


def test_a_day_without_a_lock_starts_again_at_15_minutes(client, clock):
    register(client, "mum")
    lock_out(client, clock)
    lock_out(client, clock)
    clock.value += timedelta(days=1)
    assert lock_out(client, clock) == "Too many wrong PINs. Try again in 15 minutes."


def test_a_new_pin_starts_again_at_15_minutes(client, clock):
    register(client, "kid", role="CHILD")
    lock_out(client, clock, "kid")
    lock_out(client, clock, "kid")
    admin = admin_headers(client)
    client.put(f"{BASE_URL}/users/{user_id(client, admin, 'kid')}", json={"pin": "1234"}, headers=admin)
    assert lock_out(client, clock, "kid") == "Too many wrong PINs. Try again in 15 minutes."


def test_the_next_login_tells_about_wrong_pins(client, clock):
    register(client, "mum")
    assert attempt(client, "1234").json()["wrong_pins"] == 0
    # Five that locked the name (the refused attempt during the lock isn't checked), then three more
    lock_out(client, clock)
    wrong(client, 3)
    assert attempt(client, "1234").json()["wrong_pins"] == 8
    assert attempt(client, "1234").json()["wrong_pins"] == 0


def test_repeated_lockout_is_logged(client, clock, caplog):
    register(client, "mum")
    lock_out(client, clock)
    with caplog.at_level("WARNING"):
        lock_out(client, clock)
    assert "Login for 'mum' locked for 30 minutes after 5 wrong PINs (lockout 2 in a row)" in caplog.text
