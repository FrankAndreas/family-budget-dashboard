"""The app's people come from the family hub (spec 2026-10-30, part B).

Everyone the hub lets use this app gets a row here, linked by `hub_id`; name, role and language follow the hub. A row
the hub no longer lists is hidden (`is_active` False) with all its data, until the person comes back or a parent
deletes the data here. Rows from before the hub are linked by name the first time."""

import threading
import time

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import hub, models

REFRESH_SECONDS = 60
# After the hub failed to answer, the next try waits this long (requests go on with the people kept here)
BACKOFF_SECONDS = 10

_lock = threading.Lock()
_last = 0.0
_running = False


def forget() -> None:
    """Refresh at the next chance (tests)."""
    global _last
    _last = 0.0


def refresh(db: Session, token: str, force: bool = False) -> None:
    """Take this app's people from the hub, at most every REFRESH_SECONDS unless forced. Asked with the token of the
    person using the app; when the hub answers no one (that person has no access), nothing changes. One refresh at a
    time: other requests meanwhile go on with the people kept here instead of waiting for a slow hub."""
    global _last, _running
    with _lock:
        if _running or (not force and time.monotonic() - _last < REFRESH_SECONDS):
            return
        _running = True
    try:
        try:
            people = hub.fetch_people(token)
        except hub.HubUnavailable:
            with _lock:
                _last = time.monotonic() - REFRESH_SECONDS + BACKOFF_SECONDS
            raise
        if not people:
            return
        with _lock:
            try:
                _apply(db, people)
            except IntegrityError:
                # Another process got there first: start from what it wrote
                db.rollback()
                _apply(db, people)
            _last = time.monotonic()
    finally:
        with _lock:
            _running = False


def _apply(db: Session, people: list[hub.HubPerson]) -> None:
    rows = db.query(models.User).all()
    by_hub = {row.hub_id: row for row in rows if row.hub_id is not None}
    # Rows from before the hub are linked by name at the switch only (while no row has a hub id yet), and only to a
    # hub person of the same role: later, a new person with an old name would take over that row and its money
    at_switch = not by_hub
    unlinked = {row.username.casefold(): row for row in rows if at_switch and row.username}
    matched: dict[int, models.User] = {}
    for person in people:
        row = by_hub.get(person.id)
        if row is None:
            candidate = unlinked.get(person.name.casefold())
            if candidate is not None and candidate.role == models.UserRole(person.role):
                row = unlinked.pop(person.name.casefold())
        if row is not None:
            row.hub_id = person.id
            matched[person.id] = row
    listed = {row.id for row in matched.values()}
    hub_name = {row.id: person.name for person in people if (row := matched.get(person.id)) is not None}

    # Names are unique here too: before renaming, every row in the way steps aside (names may be swapped in the hub,
    # or a hidden person's name taken by someone new, who then keeps it)
    wanted = set(hub_name.values()) | {person.name for person in people if person.id not in matched}
    for row in rows:
        if row.id in listed and row.username != hub_name[row.id]:
            row.username = f"~{row.id}"
        elif row.id not in listed and row.username in wanted:
            row.username = f"{row.username} ({row.id[:4]})"
    db.flush()

    for person in people:
        row = matched.get(person.id)
        if row is None:
            row = models.User(
                hub_id=person.id,
                role=models.UserRole(person.role),
                # A new child starts dependent: they only read their costs until a parent switches on Jugendlohn
                has_allowance=person.role != "CHILD",
            )
            db.add(row)
        row.username = person.name
        if row.role == models.UserRole.PARENT and person.role == "CHILD":
            # A parent's money stays theirs: as a child with privacy on, the other parents don't see it
            row.privacy_enabled = True
            row.has_allowance = True
        row.role = models.UserRole(person.role)
        row.settings = {**(row.settings or {}), "language": person.language}
        row.is_active = True
    for row in rows:
        if row.id not in listed:
            row.is_active = False
    db.commit()
