import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Asking about spending in plain words (design 2026-11-27): the fake AI turns any question into this month's groceries
test('asking about spending shows the sum the app computed', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Bank', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const groceries = categories.find((c: { name: string }) => c.name === 'Groceries').id;
    // Noon on today's Swiss date: inside the current month wherever the test runs
    const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Zurich' }).format(new Date());
    await call(request, parent, 'POST', '/transactions', {
        account_id: account.id, category_id: groceries, amount: 42.5, date: `${today}T12:00:00Z`,
    });
    const month = new Date(`${today.slice(0, 7)}-15T12:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });

    const errors = await login(page, parent);
    await page.getByRole('button', { name: 'Analytics' }).click();
    const box = page.getByRole('textbox', { name: 'Ask about your spending' });
    await box.fill('What did we spend on groceries this month?');
    await box.press('Enter');
    const answer = page.getByRole('status');
    await expect(answer).toContainText(`Groceries, ${month}: CHF 42.50`);
    expect(errors).toEqual([]);
});
