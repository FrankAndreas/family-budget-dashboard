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

_lock = threading.Lock()
_last = 0.0


def forget() -> None:
    """Refresh at the next chance (tests)."""
    global _last
    _last = 0.0


def refresh(db: Session, token: str, force: bool = False) -> None:
    """Take this app's people from the hub, at most every REFRESH_SECONDS unless forced. Asked with the token of the
    person using the app; when the hub answers no one (that person has no access), nothing changes."""
    global _last
    with _lock:
        if not force and time.monotonic() - _last < REFRESH_SECONDS:
            return
        people = hub.fetch_people(token)
        if not people:
            return
        try:
            _apply(db, people)
        except IntegrityError:
            # Another process got there first: start from what it wrote
            db.rollback()
            _apply(db, people)
        _last = time.monotonic()


def _apply(db: Session, people: list[hub.HubPerson]) -> None:
    rows = db.query(models.User).all()
    by_hub = {row.hub_id: row for row in rows if row.hub_id is not None}
    unlinked = {row.username.casefold(): row for row in rows if row.hub_id is None and row.username}
    matched: dict[int, models.User] = {}
    for person in people:
        row = by_hub.get(person.id) or unlinked.pop(person.name.casefold(), None)
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
        row.role = models.UserRole(person.role)
        row.settings = {**(row.settings or {}), "language": person.language}
        row.is_active = True
    for row in rows:
        if row.id not in listed:
            row.is_active = False
    db.commit()
