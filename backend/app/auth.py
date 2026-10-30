"""Who is logged in: the family hub's login (spec 2026-10-30, part B).

At home the browser sends the hub's cookie `hub_session` (set for local.<domain>, so every family app gets it); tests
and scripts may send the same token as `Authorization: Bearer`. The hub says whose login it is and whether they may
use this app; the app's people come from the hub too (hub_people.py). No PINs here any more."""

import logging
from typing import Optional

from fastapi import Depends, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from . import database, hub, hub_people, i18n, messages, models

logger = logging.getLogger(__name__)

COOKIE = "hub_session"
# With the cookie, a change must carry this header: another site can make the browser send the cookie (sibling apps
# share the site), but not a custom header without this app allowing it (spec: CSRF)
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "budget"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def request_token(request: Request) -> tuple[Optional[str], bool]:
    """The hub token of the request, and whether it came as the cookie."""
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip(), False
    cookie = request.cookies.get(COOKIE)
    return (cookie, True) if cookie else (None, False)


def _not_logged_in() -> messages.CodedError:
    return messages.CodedError(status.HTTP_401_UNAUTHORIZED, "not_logged_in", headers={"WWW-Authenticate": "Bearer"})


def _active(db: Session, hub_id: int) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.hub_id == hub_id, models.User.is_active.is_(True)).first()


def _resolve(request: Request, db: Session) -> tuple[models.User, hub.HubPerson]:
    """The person behind the request's login. Blocking (the hub, the database): runs in a worker thread."""
    token, from_cookie = request_token(request)
    if not token:
        raise _not_logged_in()
    if from_cookie and request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise messages.CodedError(status.HTTP_403_FORBIDDEN, "csrf")
    try:
        person, access = hub.session(token)
        if person is None:
            raise _not_logged_in()
        if not access:
            raise messages.CodedError(status.HTTP_403_FORBIDDEN, "no_access")
        hub_people.refresh(db, token)
        user = _active(db, person.id)
        if user is None:
            # Given access a moment ago: the people kept here are older than that
            hub_people.refresh(db, token, force=True)
            user = _active(db, person.id)
    except hub.HubUnavailable as error:
        logger.warning("The family hub can't be reached (%s)", error)
        raise messages.CodedError(status.HTTP_503_SERVICE_UNAVAILABLE, "hub_unavailable") from None
    if user is None:
        raise messages.CodedError(status.HTTP_403_FORBIDDEN, "no_access")
    return user, person


async def get_current_user_from_token(request: Request, db: Session = Depends(database.get_db)) -> models.User:
    user, person = await run_in_threadpool(_resolve, request, db)
    # From here on, the request speaks the person's language (the hub's, which may be newer than the row's). Set here,
    # in the request's own context: a worker thread's setting wouldn't reach the endpoint
    i18n.set_current(person.language if person.language in i18n.LANGUAGES else i18n.user_language(user))
    return user


async def get_optional_user(request: Request, db: Session = Depends(database.get_db)) -> Optional[models.User]:
    """The logged-in person if the request has a valid login, else None (for endpoints open to everyone)."""
    if request_token(request)[0] is None:
        return None
    try:
        return await get_current_user_from_token(request, db)
    except messages.CodedError:
        return None
