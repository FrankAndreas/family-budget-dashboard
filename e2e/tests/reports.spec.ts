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
    await expect(page.getByText('CHF 45.50 / CHF 200.00')).toBeVisible();
    await expect(page.getByText('22.8%')).toBeVisible();

    await page.getByRole('button', { name: 'Analytics' }).click();
    await expect(page.locator('.glass-card', { hasText: 'Income (This Month)' })).toContainText("CHF 3'000.00");
    await expect(page.locator('.glass-card', { hasText: 'Expenses (This Month)' })).toContainText('CHF 45.50');
    await expect(page.locator('.glass-card', { hasText: 'Net Savings (This Month)' })).toContainText("CHF 2'954.50");
    await expect(page.getByText('Groceries').last()).toBeVisible();

    // Spending per day (UX review 2026-11-07): bars, one series without a legend, up to today only, and the month so far
    const daily = page.getByTestId('daily-spending');
    await expect(daily.getByRole('heading', { name: 'Spending per day (this month)' })).toBeVisible();
    await expect(daily).toContainText('CHF 45.50 so far');
    await expect(daily.locator('.recharts-legend-wrapper')).toHaveCount(0);
    const day = Number(today.slice(8, 10));
    const ticks = (await daily.locator('.recharts-xAxis .recharts-cartesian-axis-tick-value').allInnerTexts()).map(t => parseInt(t, 10));
    expect(Math.max(...ticks)).toBeLessThanOrEqual(day);
    // Beside the pie the amount stays on one line
    const amount = page.locator('.glass-card', { hasText: 'Spending by Category' }).getByText('CHF 45.50');
    expect((await amount.boundingBox())!.height).toBeLessThan(30);
    expect(errors).toEqual([]);
});
