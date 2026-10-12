"""Small helpers shared by the test modules."""

BASE_URL = "/api/v1"


def register(client, username, role="PARENT", pin="1234"):
    client.post(f"{BASE_URL}/register", json={"username": username, "pin": pin, "role": role})
    return login(client, username, pin)


def login(client, username, pin="1234"):
    """Auth headers for the user, or the failed response's status code."""
    response = client.post(f"{BASE_URL}/login", json={"username": username, "pin": pin})
    if response.status_code != 200:
        return response.status_code
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def user_id(client, headers, username):
    return next(u["id"] for u in client.get(f"{BASE_URL}/users", headers=headers).json() if u["username"] == username)


def category_id(client, name):
    return next(c["id"] for c in client.get(f"{BASE_URL}/categories").json() if c["name"] == name)


def create_account(client, headers, name="Bank"):
    return client.post(f"{BASE_URL}/accounts", json={"name": name, "type": "BANK"}, headers=headers).json()["id"]


def balance(client, headers, account_id):
    return next(a for a in client.get(f"{BASE_URL}/accounts", headers=headers).json() if a["id"] == account_id)[
        "balance"
    ]


def add_transaction(client, headers, account_id, category, amount, **extra):
    return client.post(
        f"{BASE_URL}/transactions",
        json={"account_id": account_id, "category_id": category, "amount": amount, **extra},
        headers=headers,
    )
