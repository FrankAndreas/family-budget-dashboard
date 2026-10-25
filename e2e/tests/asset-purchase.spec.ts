import { expect, test } from '@playwright/test';
import { call, login, newParent, tab } from './helpers';

// The dealer payment marked as the purchase: the investment takes its price and date and stops being an estimate;
// Analytics shows the tag's spending and, apart from it, what is set aside each month
test('the booking that bought an investment, and its tag in analytics', async ({ page, request }) => {
    const parent = await newParent(request);
    const me = (await call(request, parent, 'GET', '/me')).id;
    await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    const mobility = await call(request, parent, 'POST', '/tags', { name: `Mobilität ${parent.name}` });
    await call(request, parent, 'POST', '/assets',
        { name: 'Auto', price: 25000, purchase_date: '2020-01-01', lifespan_years: 10, owner_id: me, tag_id: mobility.id });
    const errors = await login(page, parent);

    await page.getByRole('button', { name: '+ Add Transaction' }).click();
    await page.getByPlaceholder('Amount (income or expense is set by the category)').fill('30000');
    await page.getByPlaceholder('Description', { exact: true }).fill('Garage Muster');
    await page.locator('form select').first().selectOption({ label: 'Transportation' });
    await page.getByLabel('For item', { exact: true }).selectOption({ label: 'For item: Auto' });
    await page.getByLabel('This is the purchase').check();
    await page.getByRole('button', { name: 'Add Transaction', exact: true }).click();
    await expect(page.getByText('Garage Muster')).toBeVisible();

    await tab(page, '📦 Investments');
    const card = page.locator('div.rounded-lg', { has: page.getByRole('heading', { name: 'Auto' }) }).last();
    await expect(card).toContainText("Bought for CHF 30'000.00");
    await expect(card).not.toContainText('estimated');

    // 30'000 over 10 years: 250 a month
    await page.getByRole('button', { name: 'Analytics' }).click();
    const row = page.locator('[data-tag-row]', { hasText: `Mobilität ${parent.name}` });
    await expect(row).toContainText("CHF 30'000.00");
    await expect(row).toContainText('CHF 250.00 / month set aside');
    expect(errors).toEqual([]);
});
