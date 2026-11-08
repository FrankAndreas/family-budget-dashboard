import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Performance review 2026-11-08: a long list draws the newest 100 bookings; older ones come with a button, and the
// search still finds every booking
test('a long booking list draws the newest and finds the old ones', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const groceries = categories.find((c: { name: string }) => c.name === 'Groceries').id;
    const total = 130;
    const start = Date.now() - total * 86400_000;
    for (let i = 0; i < total; i += 10) {
        await Promise.all(Array.from({ length: 10 }, (_, k) => call(request, parent, 'POST', '/transactions', {
            account_id: account.id, category_id: groceries, amount: 10, description: `Einkauf ${i + k}`,
            date: new Date(start + (i + k) * 86400_000).toISOString(),
        })));
    }
    const errors = await login(page, parent);
    const bookings = page.getByRole('button', { name: 'Edit transaction' });
    await expect(bookings).toHaveCount(100);
    await expect(page.getByText('Einkauf 129', { exact: true })).toBeVisible();
    await expect(page.getByText('Einkauf 0', { exact: true })).toHaveCount(0);

    await page.getByRole('button', { name: 'Show older bookings (30 more)' }).click();
    await expect(bookings).toHaveCount(total);
    await expect(page.getByText('Einkauf 0', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Show older bookings/ })).toHaveCount(0);

    // The search starts again with the newest it finds, among all bookings
    await page.getByRole('searchbox').fill('Einkauf 3');
    await expect(page.getByText('Einkauf 3', { exact: true })).toBeVisible();
    // Every word on its own: "3" is in 3, 13, 23, 30–39, ...
    const withThree = Array.from({ length: total }, (_, i) => String(i)).filter(n => n.includes('3')).length;
    await expect(bookings).toHaveCount(withThree);
    expect(errors).toEqual([]);
});
