import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Accounts tab by hand: add, rename and delete an account; add, edit and delete a transaction
test('accounts and transactions through the forms', async ({ page, request }) => {
    const parent = await newParent(request);
    const errors = await login(page, parent);

    await page.getByRole('button', { name: '+ Add Account' }).click();
    await page.getByPlaceholder('Account Name').fill('Wallet');
    await page.locator('form select').selectOption('CASH');
    await page.getByRole('button', { name: 'Create Account' }).click();
    const card = page.locator('.cursor-pointer', { hasText: 'Wallet' });
    await expect(card).toContainText('CHF 0.00');

    // Add an expense, then change its amount
    await page.getByRole('button', { name: '+ Add Transaction' }).click();
    await page.getByPlaceholder('Amount (income or expense is set by the category)').fill('12.50');
    await page.getByPlaceholder('Description').fill('Bakery');
    const categories = await call(request, parent, 'GET', '/categories');
    const groceries = categories.find((c: { name: string }) => c.name === 'Groceries').id;
    await page.locator('form select').first().selectOption(groceries);
    await page.getByRole('button', { name: 'Add Transaction', exact: true }).click();
    await expect(page.getByText('Bakery')).toBeVisible();
    await expect(card).toContainText('CHF -12.50');

    await page.getByRole('button', { name: 'Edit transaction' }).click();
    await page.getByPlaceholder('Amount (income or expense is set by the category)').fill('20');
    await page.getByRole('button', { name: 'Save Changes' }).click();
    await expect(card).toContainText('CHF -20.00');
    await expect(page.locator('.glass-card', { hasText: 'Transactions in Selected Account' })).toContainText('1');

    await page.getByRole('button', { name: 'Delete transaction' }).click();
    await expect(page.getByText('No transactions yet')).toBeVisible();
    await expect(card).toContainText('CHF 0.00');

    // Rename the account, then delete it
    await card.getByRole('button', { name: 'Edit' }).click();
    await page.getByLabel('Account name').fill('Purse');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    const renamed = page.locator('.cursor-pointer', { hasText: 'Purse' });
    await expect(renamed).toBeVisible();
    await renamed.getByRole('button', { name: 'Delete' }).click();
    await expect(page.locator('.cursor-pointer', { hasText: 'Purse' })).toHaveCount(0);
    await expect(page.locator('.glass-card', { hasText: 'Transactions in Selected Account' })).toContainText('0');
    expect(await call(request, parent, 'GET', '/accounts')).toEqual([]);
    expect(errors).toEqual([]);
});
