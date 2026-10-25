import { expect, test } from '@playwright/test';
import { login, newParent, tab } from './helpers';

// A leased car entered in the form: the monthly load is the rate plus the buy-out saved up over the term
test('a leased car', async ({ page, request }) => {
    const parent = await newParent(request);
    const errors = await login(page, parent);
    await tab(page, '📦 Investments');

    const start = `${new Date().getFullYear()}-01-01`;
    await page.getByRole('button', { name: '+ Add Item' }).click();
    await page.getByLabel('Bought or leased').selectOption({ label: 'Leased' });
    await page.getByLabel('Name', { exact: true }).fill('Leasingauto');
    await page.getByLabel('Down payment').fill('5000');
    await page.getByLabel('Lease starts on').fill(start);
    await page.getByLabel('Kept in all (years)').fill('10');
    await page.getByLabel('Monthly rate').fill('390');
    await page.getByLabel('Term (months)').fill('48');
    await page.getByLabel('Buy-out at the end').fill('12000');
    await page.getByRole('button', { name: 'Add Item' }).click();

    const card = page.locator('div.rounded-lg', { has: page.getByRole('heading', { name: 'Leasingauto' }) }).last();
    await expect(card).toContainText(new RegExp(`Leased until .*${new Date().getFullYear() + 4}`));
    await expect(card).toContainText('Rate CHF 390.00 + CHF 250.00 for the buy-out = CHF 640.00/month');
    await expect(page.getByTestId('investments-total')).toContainText('CHF 640.00 / month');
    // A group with a lease doesn't call the down payment a purchase price
    await expect(page.locator('details', { has: card }).first()).toContainText("Purchase prices and down payments CHF 5'000.00");

    // Editing keeps it a lease
    await card.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByLabel('Monthly rate')).toHaveValue('390');
    // Filled in, the fields still say what they are
    await expect(page.locator('form label', { hasText: 'Down payment' })).toBeVisible();
    await expect(page.locator('form label', { hasText: 'Name' }).first()).toBeVisible();
    expect(errors).toEqual([]);
});
