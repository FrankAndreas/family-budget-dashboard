"""Smoke test against a running backend (used by the CI integration job on the published image).

Usage: python3 tests/smoke_test.py http://localhost:8000 [admin PIN]

The backend must have started on an empty database with INITIAL_ADMIN_PIN set to that PIN
(default 0000), so the first parent "Admin" can log in.

Only uses the standard library, so it runs without installing anything.
"""

import json
import sys
import time
import urllib.error
import urllib.request


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


def check(description, condition):
    print(f"{'ok  ' if condition else 'FAIL'} {description}")
    if not condition:
        sys.exit(1)


def main(base_url, admin_pin):
    username = f"smoke_{int(time.time())}"

    status, categories = call(base_url, "GET", "/categories")
    check("categories are seeded", status == 200 and len(categories) > 0)

    status, admin_login = call(base_url, "POST", "/login", {"username": "Admin", "pin": admin_pin})
    check("first parent 'Admin' was created on startup", status == 200)

    status, _ = call(
        base_url, "POST", "/users", {"username": username, "pin": "1234", "role": "PARENT"}, admin_login["access_token"]
    )
    check("admin adds a parent", status == 200)

    status, login = call(base_url, "POST", "/login", {"username": username, "pin": "1234"})
    check("login", status == 200 and "access_token" in login)
    token = login["access_token"]

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
    status, _ = call(base_url, "POST", "/users", {"username": f"{username}_b", "pin": "1234", "role": "PARENT"}, token)
    check("add a second parent", status == 200)
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

    status, _ = call(base_url, "GET", "/me")
    check("unauthenticated request rejected", status == 401)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000", sys.argv[2] if len(sys.argv) > 2 else "0000")
