"""Regression tests for the fixes from the 2026-10 functional review."""

import time

from jose import jwt

from helpers import (
    ADMIN,
    ADMIN_PIN,
    BASE_URL,
    admin_headers,
    add_transaction,
    balance,
    category_id,
    create_account,
    login,
    register,
    user_id,
)


class TestSetupAndAuth:
    def test_categories_seeded(self, client):
        assert len(client.get(f"{BASE_URL}/categories").json()) == 22
        # "Settle up" is only booked by settling up in the common budget
        headers = register(client, "p")
        account = create_account(client, headers)
        assert add_transaction(client, headers, account, category_id(client, "Settle up"), 5).status_code == 400

    def test_token_lasts_configured_time(self, client):
        register(client, "p")
        token = client.post(f"{BASE_URL}/login", json={"username": "p", "pin": "1234"}).json()["access_token"]
        minutes_left = (jwt.get_unverified_claims(token)["exp"] - time.time()) / 60
        assert minutes_left > 2900

    def test_pin_is_four_digits(self, client):
        admin = admin_headers(client)
        create = lambda pin: client.post(  # noqa: E731
            f"{BASE_URL}/users", json={"username": f"u{pin}", "pin": pin}, headers=admin
        ).status_code
        assert create("1234") == 200
        assert create("123") == 422
        assert create("123456") == 422
        assert create("12a4") == 422

    def test_no_public_signup(self, client):
        body = {"username": "x", "pin": "1234"}
        assert client.post(f"{BASE_URL}/users", json=body).status_code == 401
        assert client.post(f"{BASE_URL}/register", json=body).status_code in (404, 405)
        child = register(client, "kid", role="CHILD")
        assert client.post(f"{BASE_URL}/users", json=body, headers=child).status_code == 403

    def test_rename_members(self, client):
        admin = admin_headers(client)
        register(client, "Mum")
        # Before renaming Admin: the register helper logs in as "Admin"
        child = register(client, "kid", role="CHILD")
        timmy = client.post(f"{BASE_URL}/members", json={"username": "Timmy"}, headers=admin).json()
        admin_id = user_id(client, admin, ADMIN)
        rename = lambda uid, name: client.put(  # noqa: E731
            f"{BASE_URL}/users/{uid}", json={"username": name}, headers=admin
        )
        assert rename(admin_id, "  Papa ").json()["username"] == "Papa"
        assert isinstance(login(client, "Papa", ADMIN_PIN), dict)
        assert rename(timmy["id"], "Tim").json()["username"] == "Tim"
        assert rename(timmy["id"], "Tim").status_code == 200
        taken = rename(timmy["id"], "Mum")
        assert taken.status_code == 400
        assert taken.json()["detail"] == "That name is already taken"
        assert rename(timmy["id"], "   ").status_code == 422
        assert client.put(f"{BASE_URL}/users/{timmy['id']}", json={"username": "x"}, headers=child).status_code == 403

    def test_parent_resets_pin(self, client):
        admin = admin_headers(client)
        register(client, "kid", role="CHILD")
        kid_id = user_id(client, admin, "kid")
        assert client.put(f"{BASE_URL}/users/{kid_id}", json={"pin": "12"}, headers=admin).status_code == 422
        assert client.put(f"{BASE_URL}/users/{kid_id}", json={"pin": "4321"}, headers=admin).status_code == 200
        assert login(client, "kid", "1234") == 401
        assert isinstance(login(client, "kid", "4321"), dict)

    def test_rename_keeps_session(self, client):
        headers = register(client, "p")
        client.put(f"{BASE_URL}/users/{user_id(client, headers, 'p')}", json={"username": "p2"}, headers=headers)
        assert client.get(f"{BASE_URL}/me", headers=headers).json()["username"] == "p2"


class TestPinHashing:
    def test_pins_hashed_by_passlib_still_work(self, client):
        # Created by the old passlib-based code for PIN 2468; existing users must keep logging in
        from app import auth, database, models

        with database.SessionLocal() as db:
            db.add(
                models.User(
                    username="old",
                    pin_hash="$2b$12$S1D1HlTbO4cDlGTLZHyuoellJh/C78IQ6HohAdzDL0gfnvmup1Cuy",
                    role=models.UserRole.PARENT,
                )
            )
            db.commit()
        assert isinstance(login(client, "old", "2468"), dict)
        assert login(client, "old", "1111") == 401
        assert auth.verify_pin("2468", "not-a-bcrypt-hash") is False


class TestUserLifecycle:
    def test_inactive_user_locked_out(self, client):
        parent = register(client, "p")
        child = register(client, "kid", role="CHILD")
        kid_id = user_id(client, parent, "kid")
        client.put(f"{BASE_URL}/users/{kid_id}", json={"is_active": False}, headers=parent)
        assert client.get(f"{BASE_URL}/me", headers=child).status_code == 401
        assert login(client, "kid") == 403

    def test_last_parent_protected(self, client):
        # The admin is the only parent of a fresh install
        parent = admin_headers(client)
        pid = user_id(client, parent, ADMIN)
        assert client.put(f"{BASE_URL}/users/{pid}", json={"is_active": False}, headers=parent).status_code == 400
        assert client.put(f"{BASE_URL}/users/{pid}", json={"role": "CHILD"}, headers=parent).status_code == 400
        assert client.delete(f"{BASE_URL}/users/{pid}", headers=parent).status_code == 400

    def test_delete_user_removes_their_data(self, client):
        parent = register(client, "p")
        child = register(client, "kid", role="CHILD")
        account = create_account(client, child)
        add_transaction(client, child, account, category_id(client, "Groceries"), 5)
        client.delete(f"{BASE_URL}/users/{user_id(client, parent, 'kid')}", headers=parent)
        assert client.get(f"{BASE_URL}/accounts/{account}/transactions", headers=parent).status_code == 404


class TestTransactions:
    def test_category_decides_sign(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        assert add_transaction(client, headers, account, category_id(client, "Groceries"), 50).json()["amount"] == -50
        assert add_transaction(client, headers, account, category_id(client, "Salary"), -200).json()["amount"] == 200
        assert balance(client, headers, account) == 150

    def test_rejects_zero_and_unknown_category(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        assert add_transaction(client, headers, account, category_id(client, "Groceries"), 0).status_code == 422
        assert add_transaction(client, headers, account, "nope", 5).status_code == 400

    def test_edit_adjusts_balance(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        t = add_transaction(client, headers, account, category_id(client, "Groceries"), 30).json()
        client.put(f"{BASE_URL}/transactions/{t['id']}", json={"amount": 40}, headers=headers)
        assert balance(client, headers, account) == -40
        edited = client.put(
            f"{BASE_URL}/transactions/{t['id']}", json={"category_id": category_id(client, "Salary")}, headers=headers
        ).json()
        assert edited["amount"] == 40
        assert balance(client, headers, account) == 40

    def test_delete_reverses_balance(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        t = add_transaction(client, headers, account, category_id(client, "Groceries"), 30).json()
        assert client.delete(f"{BASE_URL}/transactions/{t['id']}", headers=headers).status_code == 200
        assert balance(client, headers, account) == 0
        assert client.delete(f"{BASE_URL}/transactions/{t['id']}", headers=headers).status_code == 404

    def test_pagination_returns_everything(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        groceries = category_id(client, "Groceries")
        for _ in range(105):
            add_transaction(client, headers, account, groceries, 1)
        url = f"{BASE_URL}/accounts/{account}/transactions"
        first = client.get(url, params={"skip": 0, "limit": 100}, headers=headers).json()
        second = client.get(url, params={"skip": 100, "limit": 100}, headers=headers).json()
        assert len({t["id"] for t in first + second}) == 105

    def test_dates_are_utc(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        groceries = category_id(client, "Groceries")
        t = add_transaction(client, headers, account, groceries, 1, date="2026-11-01T00:30:00+01:00").json()
        assert t["date"] == "2026-10-31T23:30:00Z"
        # Old exports have naive dates, which were always UTC
        t = add_transaction(client, headers, account, groceries, 1, date="2026-01-20T14:28:36").json()
        assert t["date"] == "2026-01-20T14:28:36Z"

    def test_amounts_rounded_to_cents(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        salary = category_id(client, "Salary")
        for _ in range(10):
            add_transaction(client, headers, account, salary, 0.1)
        assert balance(client, headers, account) == 1.0
        assert add_transaction(client, headers, account, salary, 1.005).json()["amount"] in (1.0, 1.01)


class TestAccountsAndBudgets:
    def test_account_delete_owner_only(self, client):
        mum = register(client, "mum")
        dad = register(client, "dad")
        account = create_account(client, mum)
        assert client.delete(f"{BASE_URL}/accounts/{account}", headers=dad).status_code == 403
        assert client.delete(f"{BASE_URL}/accounts/{account}", headers=mum).status_code == 200

    def test_account_rename(self, client):
        mum = register(client, "mum")
        dad = register(client, "dad")
        account = create_account(client, mum)
        response = client.put(
            f"{BASE_URL}/accounts/{account}", json={"name": "Savings", "type": "SAVINGS"}, headers=mum
        )
        assert response.json()["name"] == "Savings"
        assert response.json()["type"] == "SAVINGS"
        assert client.put(f"{BASE_URL}/accounts/{account}", json={"name": "x"}, headers=dad).status_code == 403

    def test_budget_validation(self, client):
        headers = register(client, "p")
        groceries = category_id(client, "Groceries")
        post = lambda body: client.post(f"{BASE_URL}/budgets", json=body, headers=headers).status_code  # noqa: E731
        assert post({"category_id": groceries, "limit": 0}) == 422
        assert post({"category_id": groceries, "limit": 10, "period": "WEEKLY"}) == 422
        assert post({"category_id": "nope", "limit": 10}) == 400

    def test_budget_edit_and_delete(self, client):
        headers = register(client, "p")
        budget = client.post(
            f"{BASE_URL}/budgets", json={"category_id": category_id(client, "Groceries"), "limit": 400}, headers=headers
        ).json()
        updated = client.put(
            f"{BASE_URL}/budgets/{budget['id']}", json={"limit": 450, "period": "YEARLY"}, headers=headers
        )
        assert updated.json()["limit"] == 450
        assert updated.json()["period"] == "YEARLY"
        assert client.put(f"{BASE_URL}/budgets/{budget['id']}", json={"limit": 0}, headers=headers).status_code == 422
        assert client.delete(f"{BASE_URL}/budgets/{budget['id']}", headers=headers).status_code == 200
        assert client.get(f"{BASE_URL}/budgets", headers=headers).json() == []
