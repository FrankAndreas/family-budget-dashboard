"""Smoke test against a running backend (used by the CI integration job on the published image).

Usage: python3 tests/smoke_test.py http://localhost:8080 [hub URL] [hub admin PIN]

Logins come from a family hub (FrankAndreas/family-hub, default http://localhost:8086) that started on an empty
database with INITIAL_ADMIN_PIN set to that PIN (default 0000), so its first parent "Admin" can log in; the backend's
HUB_URL points at that hub.

Only uses the standard library, so it runs without installing anything.
"""

import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile


def call(base_url, method, path, body=None, token=None):
    request = urllib.request.Request(
        f"{base_url}/api/v1{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read() or "null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or "null")


def upload(base_url, path, filename, content, token):
    """POST a file as multipart/form-data, the way the browser sends it."""
    boundary = f"smoke{int(time.time())}"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n\r\n'.encode()
        + content.encode()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        f"{base_url}/api/v1{path}",
        method="POST",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or "null")


def download(base_url, path, token):
    request = urllib.request.Request(f"{base_url}/api/v1{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request) as response:
        return response.status, response.read()


def hub_call(hub_url, method, path, body=None, token=None):
    """A call to the family hub as a logged-in person (its cookie), or to log in: then also the new login token."""
    request = urllib.request.Request(
        f"{hub_url}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Cookie": f"hub_session={token}"} if token else {})},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        cookies = response.headers.get_all("Set-Cookie") or []
        login = next((c.split(";")[0].split("=", 1)[1] for c in cookies if c.startswith("hub_session=")), None)
        return response.status, json.loads(response.read() or b"null"), login


def hub_person(hub_url, admin, name):
    """A parent in the hub with access to the budget app (the hub tile with the key "budget", made on first use)."""
    _, person, _ = hub_call(hub_url, "POST", "/api/people", {"name": name, "pin": "1234", "role": "PARENT"}, admin)
    _, tiles, _ = hub_call(hub_url, "GET", "/api/tiles/manage", token=admin)
    tile = next((t for t in tiles if t["app_key"] == "budget"), None)
    if tile is None:
        body = {"name": "Budget", "local_url": "http://localhost:8080", "app_key": "budget"}
        _, tile, _ = hub_call(hub_url, "POST", "/api/tiles", body, admin)
    hub_call(hub_url, "PATCH", f"/api/tiles/{tile['id']}", {"people": tile["people"] + [person["id"]]}, admin)
    return hub_call(hub_url, "POST", "/api/login", {"name": name, "pin": "1234"})[2]


def check(description, condition):
    print(f"{'ok  ' if condition else 'FAIL'} {description}")
    if not condition:
        sys.exit(1)


def headers_of(url):
    try:
        with urllib.request.urlopen(url) as response:
            return response.headers, response.read().decode(errors="replace")
    except urllib.error.HTTPError as error:
        return error.headers, ""


def security_headers(base_url):
    """Through nginx (issue #87): the app's pages, built files and API answers carry the security headers."""
    page_headers, page = headers_of(base_url + "/")
    if '<div id="root">' not in page:
        return  # the backend on its own: no nginx in front
    asset = page.split('src="', 1)[1].split('"', 1)[0]
    for name, (headers, _) in {
        "page": (page_headers, page),
        "built file": headers_of(base_url + asset),
        "API answer": headers_of(base_url + "/api/v1/categories"),
        "unknown API path": headers_of(base_url + "/api/v1/no-such-path"),
    }.items():
        policy = headers.get("Content-Security-Policy") or ""
        check(f"{name}: CSP allows only the app itself", "default-src 'self'" in policy)
        check(f"{name}: not shown in a frame", "frame-ancestors 'none'" in policy)
        check(f"{name}: X-Frame-Options", headers.get("X-Frame-Options") == "DENY")
        check(f"{name}: no MIME sniffing", headers.get("X-Content-Type-Options") == "nosniff")
        check(f"{name}: no referrer", headers.get("Referrer-Policy") == "no-referrer")
    check("index.html still checked on every load", page_headers.get("Cache-Control") == "no-cache")


def main(base_url, hub_url, admin_pin):
    username = f"smoke_{int(time.time())}"
    security_headers(base_url)

    status, categories = call(base_url, "GET", "/categories")
    check("categories are seeded", status == 200 and len(categories) > 0)

    status, _, admin = hub_call(hub_url, "POST", "/api/login", {"name": "Admin", "pin": admin_pin})
    check("the hub's first parent 'Admin' logs in", status == 200 and admin)

    token = hub_person(hub_url, admin, username)
    status, me = call(base_url, "GET", "/me", token=token)
    check("a parent added in the hub logs in here", status == 200 and me["username"] == username)

    status, account = call(base_url, "POST", "/accounts", {"name": "Smoke", "type": "BANK"}, token)
    check("create account", status == 200)

    groceries = next(c["id"] for c in categories if c["type"] == "EXPENSE")
    status, transaction = call(
        base_url,
        "POST",
        "/transactions",
        {"account_id": account["id"], "category_id": groceries, "amount": 12.5},
        token,
    )
    check("add expense (stored as negative)", status == 200 and transaction["amount"] == -12.5)

    status, accounts = call(base_url, "GET", "/accounts", token=token)
    smoke = next(a for a in accounts if a["id"] == account["id"])
    check("balance updated", status == 200 and smoke["balance"] == -12.5)

    # Common budget: a second parent, a split, and a shared expense
    check("add a second parent", bool(hub_person(hub_url, admin, f"{username}_b")))
    status, users = call(base_url, "GET", "/users", token=token)
    parent_ids = [u["id"] for u in users if u["role"] == "PARENT" and u["is_active"]]
    # Divide 100 evenly; the first parent gets the remainder
    even = 100 // len(parent_ids)
    shares = {pid: even + (100 - even * len(parent_ids) if i == 0 else 0) for i, pid in enumerate(parent_ids)}
    status, split = call(base_url, "POST", "/splits", {"name": f"Equal {username}", "shares": shares}, token)
    check("create a split", status == 200)
    status, _ = call(
        base_url,
        "POST",
        "/transactions",
        {"account_id": account["id"], "category_id": groceries, "amount": 30, "split_id": split["id"]},
        token,
    )
    check("add a shared expense", status == 200)
    status, balances = call(base_url, "GET", "/common/balance", token=token)
    me = next(u["id"] for u in users if u["username"] == username)
    owed = next(b["amount"] for b in balances if b["user_id"] == me)
    check("common balance counts the shared expense", status == 200 and owed > 0)

    # Export for analysis and bulk import
    status, content = download(base_url, "/export/analysis.zip", token)
    names = zipfile.ZipFile(io.BytesIO(content)).namelist()
    check("export for analysis is a ZIP with transactions", status == 200 and "transactions.csv" in names)
    category = next(c["name"] for c in categories if c["type"] == "EXPENSE")
    csv_file = f"date,account,category,amount,reference\n2026-10-12,Smoke,{category},7.5,smoke-{username}\n"
    status, result = upload(base_url, "/import/preview", "receipts.csv", csv_file, token)
    check("import preview checks the file", status == 200 and result["ok"] == 1)
    status, result = upload(base_url, "/import", "receipts.csv", csv_file, token)
    check("import books the file", status == 200 and result["imported"] == 1)
    status, result = upload(base_url, "/import/preview", "receipts.csv", csv_file, token)
    check("importing it again is recognised as a duplicate", status == 200 and result["duplicates"] == 1)

    status, _ = call(base_url, "GET", "/me")
    check("unauthenticated request rejected", status == 401)


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080",
        sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8086",
        sys.argv[3] if len(sys.argv) > 3 else "0000",
    )
