# Privacy Enforcement Documentation

## Overview

The Family Budget Dashboard implements a comprehensive privacy system that allows children to control whether parents can view their financial data. This document explains how the privacy system works and how to use it.

## Privacy Rules

### Access Control Matrix

| User Type | Can View Own Data | Can View Other Parents | Can View Children (Privacy OFF) | Can View Children (Privacy ON) |
|-----------|-------------------|------------------------|--------------------------------|-------------------------------|
| **Parent** | ✅ Yes | ❌ No | ✅ Yes | ❌ No |
| **Child** | ✅ Yes | ❌ No | ❌ No | ❌ No |

### Key Principles

1. **Self-Access**: All users can always access their own data
2. **Parent Isolation**: Parents cannot see other parents' individual accounts or transactions
3. **Child Privacy Control**: Children can enable privacy mode to hide their data from parents
4. **Default Visibility**: By default, child accounts are visible to parents (privacy_enabled = False)

## Implementation Details

### Backend Enforcement

The privacy system is enforced at the API level through the `privacy.py` middleware module:

#### Key Functions

1. **`check_account_access(db, current_user, account_id)`**
   - Verifies if a user has permission to access a specific account
   - Raises HTTP 403 if access is denied
   - Used before any account or transaction operations

2. **`check_user_access(db, current_user, target_user_id)`**
   - Verifies if a user can view another user's data
   - Enforces parent-child privacy rules

3. **`get_accessible_accounts(db, current_user)`**
   - Returns all accounts the current user has permission to view
   - Filters based on privacy settings

4. **`filter_users_by_privacy(users, current_user)`**
   - Filters a list of users based on privacy settings
   - Used in user listing endpoints

### Protected Endpoints

The following API endpoints enforce privacy controls:

- `GET /api/v1/accounts` - Returns only accessible accounts
- `GET /api/v1/accounts/{account_id}/transactions` - Checks account access
- `POST /api/v1/transactions` - Validates account ownership
- `GET /api/v1/users` - Filters users by privacy settings
- `PATCH /api/v1/me/privacy` - Updates privacy settings (child only)

### Database Schema

The `users` table includes a `privacy_enabled` boolean field:

```sql
privacy_enabled BOOLEAN DEFAULT FALSE
```

- `False` (default): Parents can view this user's data
- `True`: Only the user can view their own data

## User Guide

### For Children

#### Enabling Privacy Mode

1. Login to your account
2. Navigate to the **Settings** tab
3. Find the "Child Account Privacy" section
4. Check the "Enable privacy mode" checkbox
5. Your accounts and transactions are now hidden from parents

#### Disabling Privacy Mode

1. Navigate to the **Settings** tab
2. Uncheck the "Enable privacy mode" checkbox
3. Parents can now view your accounts and transactions

### For Parents

#### Viewing Child Accounts

- By default, you can see all child accounts that don't have privacy enabled
- These accounts appear in your account list alongside your own
- You can view transactions for any accessible child account

#### Privacy Indicators

- When a child enables privacy mode, their accounts disappear from your view
- You cannot override a child's privacy settings
- You cannot see which children have privacy enabled

## Testing

### Automated Tests

Run the privacy enforcement test suite:

```bash
python3 test_privacy.py
```

This tests:
- ✅ Parent can see child accounts (privacy disabled)
- ✅ Parent cannot see child accounts (privacy enabled)
- ✅ Child can always see their own accounts
- ✅ Privacy toggle works correctly

### Manual Testing

1. **Create Test Users**:
   - Register a parent account (e.g., "TestParent")
   - Register a child account (e.g., "TestChild")

2. **Test Default Behavior**:
   - Login as child and create an account
   - Login as parent and verify you can see the child's account

3. **Test Privacy Enabled**:
   - Login as child
   - Go to Settings and enable privacy mode
   - Logout and login as parent
   - Verify child's account is no longer visible

4. **Test Privacy Disabled**:
   - Login as child and disable privacy mode
   - Login as parent
   - Verify child's account is visible again

## Security Considerations

### What Privacy Mode Protects

✅ **Protected**:
- Account balances
- Transaction history
- Transaction descriptions
- Spending patterns

### What Privacy Mode Does NOT Protect

❌ **Not Protected**:
- Username (visible in user lists)
- User role (PARENT/CHILD)
- Existence of the account

### Best Practices

1. **For Parents**:
   - Respect children's privacy choices
   - Discuss privacy settings as a family
   - Use privacy as a teaching tool for financial independence

2. **For Children**:
   - Understand that privacy mode is not absolute security
   - Use privacy mode responsibly
   - Communicate with parents about financial goals

3. **For Administrators**:
   - Regularly test privacy enforcement
   - Monitor API logs for unauthorized access attempts
   - Keep the privacy middleware up to date

## API Examples

### Enable Privacy (Child Only)

```bash
curl -X PATCH http://localhost:8000/api/v1/me/privacy \
  -H "Authorization: Bearer <child_token>" \
  -H "Content-Type: application/json" \
  -d '{"privacy_enabled": true}'
```

### Get Accessible Accounts

```bash
curl http://localhost:8000/api/v1/accounts \
  -H "Authorization: Bearer <token>"
```

Response will only include accounts the user has permission to view.

### Attempt Unauthorized Access

```bash
curl http://localhost:8000/api/v1/accounts/<child_account_id>/transactions \
  -H "Authorization: Bearer <parent_token>"
```

If child has privacy enabled, this returns:
```json
{
  "detail": "You do not have permission to access this account"
}
```

## Troubleshooting

### Issue: Parent can still see child's account after privacy is enabled

**Solution**:
1. Verify privacy was actually enabled: Check the API response
2. Refresh the parent's view (logout/login or reload page)
3. Check backend logs for errors
4. Verify the privacy middleware is imported in `api.py`

### Issue: Child cannot enable privacy mode

**Possible Causes**:
- User is not logged in as a CHILD role
- API endpoint is not accessible
- Frontend/backend version mismatch

**Solution**:
1. Verify user role: `GET /api/v1/me`
2. Check browser console for errors
3. Verify backend is running: `docker logs budget-backend`

### Issue: Privacy toggle doesn't appear

**Solution**:
1. Verify you're logged in as a CHILD user
2. Check that `privacy_enabled` field is in the User interface
3. Refresh the page
4. Check browser console for TypeScript errors

## Future Enhancements

Potential improvements to the privacy system:

1. **Parent Override**: Allow parents to temporarily override privacy for safety
2. **Privacy Audit Log**: Track when privacy settings are changed
3. **Granular Privacy**: Allow privacy per account instead of per user
4. **Time-Based Privacy**: Automatic privacy mode during certain hours
5. **Privacy Notifications**: Alert parents when children enable privacy
6. **Shared Accounts**: Accounts that are always visible to both parent and child

## Conclusion

The privacy enforcement system provides a balance between parental oversight and child independence. It teaches children about financial privacy while allowing parents to monitor when appropriate. The system is enforced at the API level, ensuring that privacy rules cannot be bypassed through the frontend.

For questions or issues, refer to the main project documentation or open an issue on GitHub.
