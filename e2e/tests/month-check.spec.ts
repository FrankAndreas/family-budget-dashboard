import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Accounts tab: a clearing account, a month that doesn't add up, the gap booked as Unknown expense
test('month check books the gap of a clearing account', async ({ page, request }) => {
    const parent = await newParent(request);
    const errors = await login(page, parent);
    // The tab buttons start with their icon; the first one is the accounting side
    const tabs = page.getByRole('button', { name: /^(🏦|💰|🤝|📦|🧾|🎁|📈|⚙️) / });
    await expect(tabs.first()).toHaveText('🏦 Accounts');

    await page.getByRole('button', { name: '+ Add Account' }).click();
    await page.getByPlaceholder('Account Name').fill('Migros');
    await page.locator('form select').selectOption('CLEARING');
    await page.getByRole('button', { name: 'Create Account' }).click();
    // The card shows the account type by its name in the person's language (#50)
    await expect(page.getByText('Clearing (Migros, …)', { exact: true })).toBeVisible();

    const accounts = await call(request, parent, 'GET', '/accounts');
    const migros = accounts.find((a: { name: string }) => a.name === 'Migros');
    expect(migros.type).toBe('CLEARING');
    const categories = await call(request, parent, 'GET', '/categories');
    const category = (name: string) => categories.find((c: { name: string }) => c.name === name).id;
    for (const [name, amount, date] of [['Gift', 300, '2025-08-03'], ['Groceries', 250, '2025-08-04']] as const) {
        await call(request, parent, 'POST', '/transactions', { account_id: migros.id, category_id: category(name), amount, date });
    }

    // Count month-check requests: the list must not reload in a loop
    let checks = 0;
    page.on('request', r => { if (r.url().includes('/month-check')) checks++; });
    await page.reload();
    await expect(page.getByText('August 2025')).toBeVisible();
    await expect(page.getByText('not tracked CHF 50.00')).toBeVisible();
    const before = checks;
    await page.waitForTimeout(3000);
    expect(checks).toBe(before);

    await page.getByRole('button', { name: 'Book as Unknown expense' }).click();
    await expect(page.getByText('All months add up.')).toBeVisible();
    const after = await call(request, parent, 'GET', '/accounts');
    expect(after.find((a: { id: string }) => a.id === migros.id).balance).toBe(0);
    const rows = await call(request, parent, 'GET', `/accounts/${migros.id}/transactions`);
    expect(rows.some((r: { category_id: string; amount: number }) => r.category_id === category('Unknown expense') && r.amount === -50)).toBe(true);
    expect(errors).toEqual([]);
});
