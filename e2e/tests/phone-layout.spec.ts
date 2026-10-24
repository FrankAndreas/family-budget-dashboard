import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// The app on a phone (issue #88): the accounts come early, the tab row shows that it scrolls, booking rows keep their
// amount on one line and have buttons big enough to tap
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

test('the overview fits a phone', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const rent = categories.find((c: { name: string }) => c.name === 'Rent').id;
    await call(request, parent, 'POST', '/transactions',
        { account_id: account.id, category_id: rent, amount: 1850, description: 'Miete Musterweg' });
    const errors = await login(page, parent);
    await expect(page.getByText('Miete Musterweg')).toBeVisible();

    // No sideways scrolling of the whole page
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await expect(page.getByText(/Welcome back, .* \(Parent\)/)).toBeVisible();

    // The summary cards take a small part of the screen, not a whole one
    const summary = await page.getByTestId('summary-cards').boundingBox();
    expect(summary!.height).toBeLessThan(220);

    // The tab row doesn't fit: a button shows there is more and scrolls to it
    const more = page.getByRole('button', { name: 'More tabs' });
    await expect(more).toBeVisible();
    // Each tap scrolls further; at the end of the row the arrow goes away
    for (let i = 0; i < 5 && await more.isVisible(); i++) {
        await more.click();
        await page.waitForTimeout(400);
    }
    await expect(more).toHaveCount(0);
    await expect(page.getByRole('button', { name: '⚙️ Settings' })).toBeInViewport();

    // Scan receipts once on the page (in the inbox), not again above the bookings
    await expect(page.getByRole('button', { name: '📷 Scan receipts' })).toHaveCount(1);

    // The amount stays on one line; edit and delete are big enough to tap
    const amount = page.getByText("CHF -1'850.00").last();
    expect((await amount.boundingBox())!.height).toBeLessThan(36);
    for (const name of ['Edit transaction', 'Delete transaction']) {
        const box = (await page.getByRole('button', { name }).boundingBox())!;
        expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(40);
    }
    expect(errors).toEqual([]);
});
