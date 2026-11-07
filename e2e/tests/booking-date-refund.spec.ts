import { expect, test } from '@playwright/test';
import { addToHub, call, login, newParent } from './helpers';

// Functional review 2026-11-07: a booking typed in gets the day it happened (also changed later), a refund lowers its
// expense category, and a booking for a child stays the child's cost when it is split into receipt items
test('booking date and refund in the form', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    const errors = await login(page, parent);
    const categories = await call(request, parent, 'GET', '/categories');
    const clothing = categories.find((c: { name: string }) => c.name === 'Clothing').id;
    // Two days ago, in local time: the form's own date field
    const day = new Date();
    day.setDate(day.getDate() - 2);
    const twoDaysAgo = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;

    // An expense two days ago
    await page.getByRole('button', { name: '+ Add Transaction' }).click();
    await page.getByPlaceholder('Amount (income or expense is set by the category)').fill('200');
    await page.getByPlaceholder('Description').fill('Jacke');
    await page.getByLabel('Date').fill(twoDaysAgo);
    await page.locator('form select').first().selectOption(clothing);
    await page.getByRole('button', { name: 'Add Transaction', exact: true }).click();
    await expect(page.getByText('Jacke')).toBeVisible();
    const bookings = () => call(request, parent, 'GET', `/accounts/${account.id}/transactions`);
    const [jacket] = await bookings();
    const local = new Date(jacket.date);
    expect(local.getDate()).toBe(day.getDate());

    // The money back: a refund in the same category
    await page.getByRole('button', { name: '+ Add Transaction' }).click();
    await page.getByPlaceholder('Amount (income or expense is set by the category)').fill('80');
    await page.getByPlaceholder('Description').fill('Retoure Jacke');
    await page.locator('form select').first().selectOption(clothing);
    await page.getByLabel(/Money back \(refund\)/).check();
    await page.getByRole('button', { name: 'Add Transaction', exact: true }).click();
    const row = page.locator('.rounded-lg', { hasText: 'Retoure Jacke' });
    await expect(row).toContainText('refund');
    await expect(row).toContainText('+ CHF 80.00');
    await expect(page.getByTestId('spent-this-month')).toContainText('CHF 120.00');

    // Editing keeps it a refund and can move the day
    await row.getByRole('button', { name: 'Edit transaction' }).click();
    await expect(page.getByLabel(/Money back \(refund\)/)).toBeChecked();
    await page.getByLabel('Date').fill(twoDaysAgo);
    await page.getByRole('button', { name: 'Save Changes' }).click();
    await expect(row).toContainText('+ CHF 80.00');
    const refund = (await bookings()).find((b: { description: string }) => b.description === 'Retoure Jacke');
    expect(refund.amount).toBe(80);
    expect(new Date(refund.date).getDate()).toBe(day.getDate());
    expect(errors).toEqual([]);
});

test('a booking for a child stays theirs when split into items', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    // A dependent child from the hub (children without Jugendlohn are added there)
    const kid = `kind${parent.name}`;
    await addToHub(request, kid, 'CHILD');
    const child = (await call(request, parent, 'GET', '/users')).find((u: { username: string }) => u.username === kid);
    const categories = await call(request, parent, 'GET', '/categories');
    const clothing = categories.find((c: { name: string }) => c.name === 'Clothing').id;
    await call(request, parent, 'POST', '/transactions',
        { account_id: account.id, category_id: clothing, amount: 60, description: 'Kinderjacke', member_id: child.id });
    const errors = await login(page, parent);

    await page.locator('.rounded-lg', { hasText: 'Kinderjacke' }).getByRole('button', { name: '🧾 Split into items' }).click();
    await expect(page.getByLabel('Person of item 1')).toHaveValue(child.id);
    await page.locator('form').getByRole('button', { name: 'Book', exact: true }).click();
    await expect.poll(async () => {
        const summary = await call(request, parent, 'GET', '/reports/summary?range=month');
        return summary.by_child.map((c: { amount: number }) => c.amount);
    }).toEqual([60]);
    expect(errors).toEqual([]);
});
