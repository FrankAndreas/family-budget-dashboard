import { expect, test, type Page } from '@playwright/test';
import { call, login, newParent, tab } from './helpers';

// Editing an entry far down a long list brings its form (above the list) into view, filled in; on a phone the
// form was off screen and nothing seemed to happen
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

async function editLast(page: Page, edit: string) {
    const button = page.getByRole('button', { name: edit, exact: true }).last();
    await button.scrollIntoViewIfNeeded();
    await button.click();
}

test('the form comes into view when editing an entry far down', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const rent = categories.find((c: { name: string }) => c.name === 'Rent').id;
    const me = (await call(request, parent, 'GET', '/me')).id;
    for (let i = 1; i <= 12; i++) {
        await call(request, parent, 'POST', '/assets',
            { name: `Gerät ${i}`, price: 100 * i, purchase_date: '2024-01-15', lifespan_years: 5, owner_id: me });
        await call(request, parent, 'POST', '/planned-costs',
            { name: `Rechnung ${i}`, category_id: rent, amount: 50 * i, frequency: 'YEARLY', due_month: (i % 12) + 1, owner_id: me });
    }
    for (let i = 1; i <= 30; i++) {
        await call(request, parent, 'POST', '/transactions',
            { account_id: account.id, category_id: rent, amount: i, description: `Buchung ${i}`, date: `2026-01-${String(i).padStart(2, '0')}` });
    }
    const errors = await login(page, parent);

    await expect(page.getByText('Buchung 30')).toBeVisible();
    await editLast(page, 'Edit transaction');
    await expect(page.getByPlaceholder('Description', { exact: true })).toBeInViewport();
    await expect(page.getByPlaceholder('Description', { exact: true })).toHaveValue('Buchung 1');

    await tab(page, '📦 Investments');
    // On a phone the groups start folded
    await page.getByText('No tag', { exact: true }).click();
    await expect(page.getByText('Gerät 12')).toBeVisible();
    await editLast(page, 'Edit');
    await expect(page.getByLabel('Name', { exact: true })).toBeInViewport();
    await expect(page.getByLabel('Name', { exact: true })).not.toHaveValue('');
    // Why the other parent or a child with own allowance is not in the owner list
    await expect(page.getByText('Others appear here once they let you manage their money (Settings → Sharing).')).toBeVisible();

    await tab(page, '🧾 Yearly bills');
    await expect(page.getByText('Rechnung 12')).toBeVisible();
    await editLast(page, 'Edit bill');
    await expect(page.getByLabel('Name', { exact: true })).toBeInViewport();
    await expect(page.getByLabel('Name', { exact: true })).not.toHaveValue('');
    expect(errors).toEqual([]);
});
