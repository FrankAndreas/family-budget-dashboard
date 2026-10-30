"""The family hub (FrankAndreas/family-hub): who is logged in, and the people of this app (spec 2026-10-30, part B).

The hub's login is a token (the `hub_session` cookie at home). This app passes it to the hub as a Bearer token and never
logs it. Session answers are kept for a minute, so a "log out everywhere" in the hub counts here within a minute."""

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

CACHE_SECONDS = 60
TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class HubPerson:
    id: int
    name: str
    role: str
    color: Optional[str]
    language: str


class HubUnavailable(Exception):
    """The hub didn't answer, or not as expected: nobody is let in."""


# An empty setting counts as unset (docker-compose passes HUB_URL=${HUB_URL:-})
def hub_url() -> str:
    """How this backend reaches the hub, e.g. http://<NAS_IP>:8086."""
    return (os.getenv("HUB_URL") or "http://localhost:8086").rstrip("/")


def public_url() -> str:
    """Where browsers log in, e.g. https://home.local.<domain>."""
    return (os.getenv("HUB_PUBLIC_URL") or hub_url()).rstrip("/")


def app_key() -> str:
    """This app's key in the hub (Einstellungen → Apps)."""
    return os.getenv("HUB_APP_KEY") or "budget"


def _person(data: dict) -> HubPerson:
    return HubPerson(
        id=int(data["id"]),
        name=str(data["name"]),
        role=str(data["role"]),
        color=data.get("color"),
        language=str(data.get("language") or "de"),
    )


def _get(path: str, token: str) -> tuple[int, object]:
    request = urllib.request.Request(f"{hub_url()}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310 - the hub's own URL
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, OSError, ValueError) as error:
        # Only the kind of failure: the URL carries no token, but keep messages short and free of request details
        raise HubUnavailable(type(error).__name__) from None


def fetch_session(token: str) -> tuple[Optional[HubPerson], bool]:
    """The person the token belongs to and whether they may use this app; (None, False) when it's no valid login."""
    status, body = _get(f"/api/session?app={urllib.parse.quote(app_key())}", token)
    if status != 200 or not isinstance(body, dict):
        raise HubUnavailable(f"session answered {status}")
    if not body.get("valid") or not body.get("person"):
        return None, False
    return _person(body["person"]), bool(body.get("access"))


def fetch_people(token: str) -> list[HubPerson]:
    """Everyone the hub lets use this app; [] when the token's person may not ask (no access or no login)."""
    status, body = _get(f"/api/apps/{urllib.parse.quote(app_key())}/people", token)
    if status in (401, 403):
        return []
    if status != 200 or not isinstance(body, list):
        raise HubUnavailable(f"people answered {status}")
    return [_person(item) for item in body]


_cache: dict[str, tuple[float, tuple[Optional[HubPerson], bool]]] = {}
_lock = threading.Lock()


def session(token: str) -> tuple[Optional[HubPerson], bool]:
    """fetch_session, kept for CACHE_SECONDS per token (keyed by its hash, never the token itself). Only a valid login
    with access is kept: someone given access a moment ago gets in at once."""
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        for stale in [k for k, (at, _) in _cache.items() if now - at >= CACHE_SECONDS]:
            del _cache[stale]
        if key in _cache:
            return _cache[key][1]
    found = fetch_session(token)
    if found[0] is not None and found[1]:
        with _lock:
            _cache[key] = (now, found)
    return found


def forget(token: Optional[str] = None) -> None:
    """Drop the kept answer for one login (logging out), or all of them (tests)."""
    with _lock:
        if token is None:
            _cache.clear()
        else:
            _cache.pop(hashlib.sha256(token.encode()).hexdigest(), None)
