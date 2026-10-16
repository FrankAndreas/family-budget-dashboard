import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Budgets and Analytics show the numbers the server calculates (Swiss time)
test('budget spending and analytics totals', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Bank', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const category = (name: string) => categories.find((c: { name: string }) => c.name === name).id;
    // Noon on today's Swiss date: inside the current month wherever the test runs
    const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Zurich' }).format(new Date());
    for (const [name, amount] of [['Salary', 3000], ['Groceries', 45.5]] as const) {
        await call(request, parent, 'POST', '/transactions', {
            account_id: account.id, category_id: category(name), amount, date: `${today}T12:00:00Z`,
        });
    }
    await call(request, parent, 'POST', '/budgets', { category_id: category('Groceries'), limit: 200, period: 'MONTHLY' });

    const errors = await login(page, parent);
    await page.getByRole('button', { name: 'Budgets' }).click();
    await expect(page.getByText('$45.50 / $200.00')).toBeVisible();
    await expect(page.getByText('22.8%')).toBeVisible();

    await page.getByRole('button', { name: 'Analytics' }).click();
    await expect(page.locator('.glass-card', { hasText: 'Income (This Month)' })).toContainText('$3000.00');
    await expect(page.locator('.glass-card', { hasText: 'Expenses (This Month)' })).toContainText('$45.50');
    await expect(page.locator('.glass-card', { hasText: 'Net Savings (This Month)' })).toContainText('$2954.50');
    await expect(page.getByText('Groceries').last()).toBeVisible();
    expect(errors).toEqual([]);
});
