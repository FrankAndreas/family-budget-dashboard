"""Fixes from the security review of the family-hub login (2026-10-30)."""

import threading

import fake_hub
from helpers import BASE_URL, ADMIN, admin_headers, bearer, create_account, register, user_id

from app import database, hub, hub_people, models


def old_row(name, role="PARENT"):
    """A person from before the family hub: no hub id yet."""
    with database.SessionLocal() as db:
        row = models.User(username=name, role=models.UserRole(role), has_allowance=True)
        db.add(row)
        db.commit()
        return row.id


def row(user_id_):
    with database.SessionLocal() as db:
        return db.query(models.User).filter(models.User.id == user_id_).one()


# 1. Rows from before the hub are linked by name at the switch only, never later
def test_old_rows_linked_by_name_only_at_the_switch(client, family_hub):
    beat = old_row("Beat")
    client.get(f"{BASE_URL}/me", headers=admin_headers(client))
    # Months later someone new gets that name in the hub: a new person, not the old row and its money
    family_hub.add("beat", "PARENT")
    client.get(f"{BASE_URL}/users", headers=admin_headers(client))
    assert row(beat).hub_id is None
    assert row(beat).is_active is False


def test_name_link_needs_the_same_role(client, family_hub):
    with database.SessionLocal() as db:
        db.query(models.User).delete()
        db.commit()
    mum = old_row("Mum")
    kid = old_row("Kid", "CHILD")
    family_hub.add("Mum", "PARENT")
    # The hub calls "Kid" a parent: not the old child row
    family_hub.add("Kid", "PARENT")
    client.get(f"{BASE_URL}/me", headers=bearer(fake_hub.token("Mum")))
    assert row(mum).hub_id == family_hub.people["Mum"].id
    assert row(kid).hub_id is None


# 2. A parent the hub turns into a child keeps their money private from the other parents
def test_parent_turned_child_stays_private(client, family_hub):
    mum = register(client, "mum")
    dad = register(client, "dad")
    dad_account = create_account(client, dad, "Dad bank")
    family_hub.set_role("dad", "CHILD")
    client.get(f"{BASE_URL}/users", headers=mum)
    assert dad_account not in [a["id"] for a in client.get(f"{BASE_URL}/accounts", headers=mum).json()]
    assert row(user_id(client, dad, "dad")).privacy_enabled is True


# 3. Logging out happens in the hub now (it ends the login there, for every app): this app has no logout of its own


# 4. The app is home-only: nothing that came through the Cloudflare tunnel counts as a login
def test_no_login_through_the_tunnel(client):
    headers = {**admin_headers(client), "Cf-Connecting-Ip": "203.0.113.7"}
    response = client.get(f"{BASE_URL}/me", headers=headers)
    assert response.status_code == 401


# 5. A slow or unreachable hub doesn't hold up every request
def test_one_refresh_at_a_time(client, family_hub, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow(tok):
        calls.append(tok)
        started.set()
        release.wait(5)
        return []

    monkeypatch.setattr(hub, "fetch_people", slow)
    hub_people.forget()
    with database.SessionLocal() as db1:
        first = threading.Thread(target=hub_people.refresh, args=(db1, "tok-Admin", True))
        first.start()
        assert started.wait(5)
        with database.SessionLocal() as db2:
            # Another request meanwhile goes on with the people it has instead of waiting
            hub_people.refresh(db2, "tok-Admin", force=True)
        release.set()
        first.join()
    assert len(calls) == 1


def test_hub_down_backs_off(client, family_hub, monkeypatch):
    calls = []

    def down(tok):
        calls.append(tok)
        raise hub.HubUnavailable("down")

    monkeypatch.setattr(hub, "fetch_people", down)
    hub_people.forget()
    with database.SessionLocal() as db:
        for _ in range(3):
            try:
                hub_people.refresh(db, "tok-Admin")
            except hub.HubUnavailable:
                pass
    assert len(calls) == 1


# A machine that started less than a minute ago (a fresh CI runner, the NAS after a restart) still refreshes at first
def test_first_refresh_soon_after_boot(client, family_hub, monkeypatch):
    calls = []
    monkeypatch.setattr(hub, "fetch_people", lambda tok: calls.append(tok) or [])
    monkeypatch.setattr(hub_people.time, "monotonic", lambda: 5.0)
    hub_people.forget()
    with database.SessionLocal() as db:
        hub_people.refresh(db, "tok-Admin")
    assert calls == ["tok-Admin"]
