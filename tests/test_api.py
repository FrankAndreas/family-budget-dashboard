"""
Comprehensive test suite for the Family Budget Dashboard backend.
Tests authentication, CRUD operations, privacy enforcement, and business logic.
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from app.main import app

# Runs the API in-process against the temporary database set up in conftest.py
client = TestClient(app)
BASE_URL = "/api/v1"


class TestAuthentication:
    """Test authentication and user management"""

    def test_register_user(self):
        """Test user registration"""
        response = client.post(
            f"{BASE_URL}/register",
            json={"username": f"test_user_{datetime.now().timestamp()}", "pin": "1234", "role": "PARENT"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "username" in data
        assert data["role"] == "PARENT"

    def test_register_duplicate_user(self):
        """Test that duplicate usernames are rejected"""
        username = f"duplicate_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        response = client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        assert response.status_code == 400

    def test_login_success(self):
        """Test successful login"""
        username = f"login_test_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        response = client.post(f"{BASE_URL}/login", json={"username": username, "pin": "1234"})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_pin(self):
        """Test login with wrong PIN"""
        username = f"wrong_pin_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        response = client.post(f"{BASE_URL}/login", json={"username": username, "pin": "9999"})
        assert response.status_code == 401

    def test_get_current_user(self):
        """Test getting current user info"""
        username = f"current_user_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        token_response = client.post(f"{BASE_URL}/login", json={"username": username, "pin": "1234"})
        token = token_response.json()["access_token"]

        response = client.get(f"{BASE_URL}/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == username


class TestAccountManagement:
    """Test account CRUD operations"""

    @pytest.fixture
    def auth_token(self):
        """Create a user and return auth token"""
        username = f"account_test_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        response = client.post(f"{BASE_URL}/login", json={"username": username, "pin": "1234"})
        return response.json()["access_token"]

    def test_create_account(self, auth_token):
        """Test creating an account"""
        response = client.post(
            f"{BASE_URL}/accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"name": "Test Account", "type": "BANK"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Account"
        assert data["type"] == "BANK"
        assert data["balance"] == 0.0

    def test_get_accounts(self, auth_token):
        """Test getting user's accounts"""
        # Create an account first
        client.post(
            f"{BASE_URL}/accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"name": "Test Account", "type": "CASH"},
        )

        response = client.get(f"{BASE_URL}/accounts", headers={"Authorization": f"Bearer {auth_token}"})
        assert response.status_code == 200
        accounts = response.json()
        assert isinstance(accounts, list)
        assert len(accounts) > 0


class TestTransactionManagement:
    """Test transaction operations"""

    @pytest.fixture
    def setup_account(self):
        """Create user, login, and create account"""
        username = f"trans_test_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        token_response = client.post(f"{BASE_URL}/login", json={"username": username, "pin": "1234"})
        token = token_response.json()["access_token"]

        account_response = client.post(
            f"{BASE_URL}/accounts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Test Account", "type": "BANK"},
        )
        account_id = account_response.json()["id"]

        # Get a category
        categories = client.get(f"{BASE_URL}/categories", headers={"Authorization": f"Bearer {token}"}).json()
        category_id = categories[0]["id"]

        return token, account_id, category_id

    def test_create_transaction(self, setup_account):
        """Test creating a transaction"""
        token, account_id, category_id = setup_account

        response = client.post(
            f"{BASE_URL}/transactions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "account_id": account_id,
                "category_id": category_id,
                "amount": 100.50,
                "description": "Test transaction",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["amount"] == 100.50
        assert data["description"] == "Test transaction"

    def test_account_balance_update(self, setup_account):
        """Test that account balance updates after transaction"""
        token, account_id, category_id = setup_account

        # Create transaction
        client.post(
            f"{BASE_URL}/transactions",
            headers={"Authorization": f"Bearer {token}"},
            json={"account_id": account_id, "category_id": category_id, "amount": 500.00, "description": "Income"},
        )

        # Check account balance
        accounts = client.get(f"{BASE_URL}/accounts", headers={"Authorization": f"Bearer {token}"}).json()

        account = next(acc for acc in accounts if acc["id"] == account_id)
        assert account["balance"] == 500.00

    def test_get_transactions(self, setup_account):
        """Test getting transactions for an account"""
        token, account_id, category_id = setup_account

        # Create a transaction
        client.post(
            f"{BASE_URL}/transactions",
            headers={"Authorization": f"Bearer {token}"},
            json={"account_id": account_id, "category_id": category_id, "amount": 50.00, "description": "Test"},
        )

        response = client.get(
            f"{BASE_URL}/accounts/{account_id}/transactions", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        transactions = response.json()
        assert isinstance(transactions, list)
        assert len(transactions) > 0


class TestBudgetManagement:
    """Test budget operations"""

    @pytest.fixture
    def auth_setup(self):
        """Create user and get token with category"""
        username = f"budget_test_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        token_response = client.post(f"{BASE_URL}/login", json={"username": username, "pin": "1234"})
        token = token_response.json()["access_token"]

        categories = client.get(f"{BASE_URL}/categories", headers={"Authorization": f"Bearer {token}"}).json()
        category_id = next(c["id"] for c in categories if c["type"] == "EXPENSE")

        return token, category_id

    def test_create_budget(self, auth_setup):
        """Test creating a budget"""
        token, category_id = auth_setup

        response = client.post(
            f"{BASE_URL}/budgets",
            headers={"Authorization": f"Bearer {token}"},
            json={"category_id": category_id, "limit": 500.00, "period": "MONTHLY"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 500.00
        assert data["period"] == "MONTHLY"

    def test_get_budgets(self, auth_setup):
        """Test getting user's budgets"""
        token, category_id = auth_setup

        # Create a budget
        client.post(
            f"{BASE_URL}/budgets",
            headers={"Authorization": f"Bearer {token}"},
            json={"category_id": category_id, "limit": 300.00, "period": "MONTHLY"},
        )

        response = client.get(f"{BASE_URL}/budgets", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        budgets = response.json()
        assert isinstance(budgets, list)
        assert len(budgets) > 0


class TestPrivacyEnforcement:
    """Test privacy controls"""

    def test_parent_sees_child_without_privacy(self):
        """Test parent can see child's data when privacy is disabled"""
        # Create parent
        parent_username = f"parent_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": parent_username, "pin": "1111", "role": "PARENT"})
        parent_token = client.post(f"{BASE_URL}/login", json={"username": parent_username, "pin": "1111"}).json()[
            "access_token"
        ]

        # Create child
        child_username = f"child_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": child_username, "pin": "2222", "role": "CHILD"})
        child_token = client.post(f"{BASE_URL}/login", json={"username": child_username, "pin": "2222"}).json()[
            "access_token"
        ]

        # Child creates account
        child_account = client.post(
            f"{BASE_URL}/accounts",
            headers={"Authorization": f"Bearer {child_token}"},
            json={"name": "Child Account", "type": "CASH"},
        ).json()

        # Parent should see child's account
        parent_accounts = client.get(f"{BASE_URL}/accounts", headers={"Authorization": f"Bearer {parent_token}"}).json()

        account_names = [acc["name"] for acc in parent_accounts]
        assert "Child Account" in account_names

    def test_parent_cannot_see_child_with_privacy(self):
        """Test parent cannot see child's data when privacy is enabled"""
        # Create parent
        parent_username = f"parent_priv_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": parent_username, "pin": "1111", "role": "PARENT"})
        parent_token = client.post(f"{BASE_URL}/login", json={"username": parent_username, "pin": "1111"}).json()[
            "access_token"
        ]

        # Create child
        child_username = f"child_priv_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": child_username, "pin": "2222", "role": "CHILD"})
        child_token = client.post(f"{BASE_URL}/login", json={"username": child_username, "pin": "2222"}).json()[
            "access_token"
        ]

        # Child creates account
        client.post(
            f"{BASE_URL}/accounts",
            headers={"Authorization": f"Bearer {child_token}"},
            json={"name": "Private Account", "type": "CASH"},
        )

        # Child enables privacy
        client.patch(
            f"{BASE_URL}/me/privacy", headers={"Authorization": f"Bearer {child_token}"}, json={"privacy_enabled": True}
        )

        # Parent should NOT see child's account
        parent_accounts = client.get(f"{BASE_URL}/accounts", headers={"Authorization": f"Bearer {parent_token}"}).json()

        account_names = [acc["name"] for acc in parent_accounts]
        assert "Private Account" not in account_names

    def test_child_can_toggle_privacy(self):
        """Test child can enable and disable privacy"""
        child_username = f"child_toggle_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": child_username, "pin": "2222", "role": "CHILD"})
        child_token = client.post(f"{BASE_URL}/login", json={"username": child_username, "pin": "2222"}).json()[
            "access_token"
        ]

        # Enable privacy
        response = client.patch(
            f"{BASE_URL}/me/privacy", headers={"Authorization": f"Bearer {child_token}"}, json={"privacy_enabled": True}
        )
        assert response.status_code == 200
        assert response.json()["privacy_enabled"] == True

        # Disable privacy
        response = client.patch(
            f"{BASE_URL}/me/privacy",
            headers={"Authorization": f"Bearer {child_token}"},
            json={"privacy_enabled": False},
        )
        assert response.status_code == 200
        assert response.json()["privacy_enabled"] == False

    def test_parent_cannot_toggle_privacy(self):
        """Test parent cannot modify privacy settings"""
        parent_username = f"parent_no_priv_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": parent_username, "pin": "1111", "role": "PARENT"})
        parent_token = client.post(f"{BASE_URL}/login", json={"username": parent_username, "pin": "1111"}).json()[
            "access_token"
        ]

        response = client.patch(
            f"{BASE_URL}/me/privacy",
            headers={"Authorization": f"Bearer {parent_token}"},
            json={"privacy_enabled": True},
        )
        assert response.status_code == 403


class TestCategories:
    """Test category operations"""

    def test_get_categories(self):
        """Test getting all categories"""
        # Create a user to get token
        username = f"cat_test_{datetime.now().timestamp()}"
        client.post(f"{BASE_URL}/register", json={"username": username, "pin": "1234", "role": "PARENT"})
        token = client.post(f"{BASE_URL}/login", json={"username": username, "pin": "1234"}).json()["access_token"]

        response = client.get(f"{BASE_URL}/categories", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        categories = response.json()
        assert isinstance(categories, list)
        assert len(categories) >= 15  # We seeded 15 categories


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
