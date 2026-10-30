"""Small helpers shared by the test modules."""

BASE_URL = "/api/v1"

# The first parent every test database starts with (see conftest.py)
ADMIN = "Admin"


def admin_headers(client):
    return login(client, ADMIN)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, username, role="PARENT", pin=None, by=None):
    """A family member added in the (fake) hub with access to the app, logged in. A child added this way has their own
    allowance (Jugendlohn), as a parent would switch it on; add_member() adds a dependent child. `pin` and `by` are
    from before the family hub and ignored."""
    import fake_hub
    from app import database, models

    headers = bearer(fake_hub.current.add(username, role))
    # The first request makes the app's row for the new person
    assert client.get(f"{BASE_URL}/me", headers=headers).status_code == 200
    if role == "CHILD":
        with database.SessionLocal() as db:
            db.query(models.User).filter(models.User.username == username).update({"has_allowance": True})
            db.commit()
    return headers


def add_member(client, name):
    """A dependent child (no Jugendlohn) in the hub with access to the app; returns their id in the app."""
    import fake_hub

    hub = fake_hub.current
    hub.add(name, "CHILD")
    parent = next(n for n in sorted(hub.access) if hub.people[n].role == "PARENT")
    return user_id(client, bearer(fake_hub.token(parent)), name)


def remove_from_hub(name):
    """The hub no longer lists the person for this app (was: deactivating them here); their data stays, hidden."""
    import fake_hub

    fake_hub.current.remove_access(name)


def remove_id_from_hub(person_id):
    """remove_from_hub() for a person known by their id in the app (before deleting their data here)."""
    from app import database, models

    with database.SessionLocal() as db:
        remove_from_hub(db.query(models.User).filter(models.User.id == person_id).one().username)


def set_language(headers, language):
    """The person (by their login headers) picks a language in the hub, where it now lives."""
    import fake_hub

    name = headers["Authorization"].removeprefix("Bearer tok-")
    fake_hub.current.set_language(name, language)


def login(client, username, pin=None):
    """Auth headers for a person the (fake) hub knows, or 401 for anyone else."""
    import fake_hub

    if username not in fake_hub.current.people:
        return 401
    return bearer(fake_hub.token(username))


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


def create_split(client, headers, name, shares):
    """shares: {user_id: percent}"""
    return client.post(f"{BASE_URL}/splits", json={"name": name, "shares": shares}, headers=headers)


def balance_of(client, headers, uid):
    """What the parent is owed (positive) or owes (negative) in the common budget."""
    rows = client.get(f"{BASE_URL}/common/balance", headers=headers).json()
    return next((row["amount"] for row in rows if row["user_id"] == uid), 0.0)
