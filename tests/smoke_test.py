"""Smoke test against a running backend (used by the CI integration job on the published image).

Usage: python3 tests/smoke_test.py http://localhost:8000

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


def main(base_url):
    username = f"smoke_{int(time.time())}"

    status, categories = call(base_url, "GET", "/categories")
    check("categories are seeded", status == 200 and len(categories) > 0)

    status, _ = call(base_url, "POST", "/register", {"username": username, "pin": "1234", "role": "PARENT"})
    check("register parent", status == 200)

    status, login = call(base_url, "POST", "/login", {"username": username, "pin": "1234"})
    check("login", status == 200 and "access_token" in login)
    token = login["access_token"]

    status, account = call(base_url, "POST", "/accounts", {"name": "Smoke", "type": "BANK"}, token)
    check("create account", status == 200)

    groceries = next(c["id"] for c in categories if c["type"] == "EXPENSE")
    status, transaction = call(
        base_url, "POST", "/transactions", {"account_id": account["id"], "category_id": groceries, "amount": 12.5}, token
    )
    check("add expense (stored as negative)", status == 200 and transaction["amount"] == -12.5)

    status, accounts = call(base_url, "GET", "/accounts", token=token)
    smoke = next(a for a in accounts if a["id"] == account["id"])
    check("balance updated", status == 200 and smoke["balance"] == -12.5)

    status, _ = call(base_url, "GET", "/me")
    check("unauthenticated request rejected", status == 401)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000")
