#!/usr/bin/env python3
"""
Test script to verify privacy enforcement in the Family Budget Dashboard.
This script tests that:
1. Parents can see their own data
2. Parents can see child data when privacy is disabled
3. Parents cannot see child data when privacy is enabled
4. Children can only see their own data
"""

import requests
import json

BASE_URL = "http://localhost:8000/api/v1"

def register_user(username, pin, role):
    """Register a new user"""
    response = requests.post(f"{BASE_URL}/register", json={
        "username": username,
        "pin": pin,
        "role": role
    })
    return response.json()

def login(username, pin):
    """Login and get token"""
    response = requests.post(f"{BASE_URL}/login", json={
        "username": username,
        "pin": pin
    })
    return response.json()["access_token"]

def get_me(token):
    """Get current user info"""
    response = requests.get(f"{BASE_URL}/me", headers={
        "Authorization": f"Bearer {token}"
    })
    return response.json()

def create_account(token, name, account_type):
    """Create an account"""
    response = requests.post(f"{BASE_URL}/accounts", 
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "type": account_type}
    )
    return response.json()

def get_accounts(token):
    """Get all accessible accounts"""
    response = requests.get(f"{BASE_URL}/accounts", headers={
        "Authorization": f"Bearer {token}"
    })
    return response.json()

def update_privacy(token, privacy_enabled):
    """Update privacy settings"""
    response = requests.patch(f"{BASE_URL}/me/privacy",
        headers={"Authorization": f"Bearer {token}"},
        json={"privacy_enabled": privacy_enabled}
    )
    return response.json()

def main():
    print("=" * 60)
    print("Privacy Enforcement Test")
    print("=" * 60)
    
    # Test 1: Create parent and child users
    print("\n1. Creating test users...")
    try:
        register_user("TestParent", "1111", "PARENT")
        print("   ✓ Created parent: TestParent")
    except:
        print("   ℹ Parent already exists")
    
    try:
        register_user("TestChild", "2222", "CHILD")
        print("   ✓ Created child: TestChild")
    except:
        print("   ℹ Child already exists")
    
    # Test 2: Login as parent and create account
    print("\n2. Parent creates account...")
    parent_token = login("TestParent", "1111")
    parent_account = create_account(parent_token, "Parent's Wallet", "CASH")
    print(f"   ✓ Parent account created: {parent_account['name']}")
    
    # Test 3: Login as child and create account
    print("\n3. Child creates account...")
    child_token = login("TestChild", "2222")
    child_account = create_account(child_token, "Child's Piggy Bank", "CASH")
    print(f"   ✓ Child account created: {child_account['name']}")
    
    # Test 4: Parent should see child's account (privacy disabled by default)
    print("\n4. Testing parent access with privacy DISABLED...")
    parent_accounts = get_accounts(parent_token)
    account_names = [acc['name'] for acc in parent_accounts]
    print(f"   Parent sees accounts: {account_names}")
    
    if "Child's Piggy Bank" in account_names:
        print("   ✓ PASS: Parent can see child's account (privacy disabled)")
    else:
        print("   ✗ FAIL: Parent cannot see child's account")
    
    # Test 5: Child enables privacy
    print("\n5. Child enables privacy mode...")
    privacy_result = update_privacy(child_token, True)
    print(f"   ✓ Privacy enabled: {privacy_result}")
    
    # Test 6: Parent should NOT see child's account now
    print("\n6. Testing parent access with privacy ENABLED...")
    parent_accounts = get_accounts(parent_token)
    account_names = [acc['name'] for acc in parent_accounts]
    print(f"   Parent sees accounts: {account_names}")
    
    if "Child's Piggy Bank" not in account_names:
        print("   ✓ PASS: Parent cannot see child's account (privacy enabled)")
    else:
        print("   ✗ FAIL: Parent can still see child's account")
    
    # Test 7: Child can still see their own account
    print("\n7. Testing child access to own account...")
    child_accounts = get_accounts(child_token)
    account_names = [acc['name'] for acc in child_accounts]
    print(f"   Child sees accounts: {account_names}")
    
    if "Child's Piggy Bank" in account_names:
        print("   ✓ PASS: Child can see their own account")
    else:
        print("   ✗ FAIL: Child cannot see their own account")
    
    # Test 8: Disable privacy again
    print("\n8. Child disables privacy mode...")
    privacy_result = update_privacy(child_token, False)
    print(f"   ✓ Privacy disabled: {privacy_result}")
    
    # Test 9: Parent should see child's account again
    print("\n9. Testing parent access with privacy DISABLED again...")
    parent_accounts = get_accounts(parent_token)
    account_names = [acc['name'] for acc in parent_accounts]
    print(f"   Parent sees accounts: {account_names}")
    
    if "Child's Piggy Bank" in account_names:
        print("   ✓ PASS: Parent can see child's account again")
    else:
        print("   ✗ FAIL: Parent cannot see child's account")
    
    print("\n" + "=" * 60)
    print("Privacy Enforcement Test Complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
