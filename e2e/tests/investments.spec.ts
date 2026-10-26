import { expect, test } from '@playwright/test';
import { call, login, newParent, tab } from './helpers';

// Investments grouped by tag, with totals per group and overall; a new tag from the form; archived items leave the
// totals and come back with Restore
test('investments by tag, archived and restored', async ({ page, request }) => {
    const parent = await newParent(request);
    const me = (await call(request, parent, 'GET', '/me')).id;
    // Tags are family-wide and the browser tests share a database: names of their own
    const mobility = await call(request, parent, 'POST', '/tags', { name: `Mobilität ${parent.name}`, icon: '🚗' });
    const nextYear = new Date().getFullYear() + 1;
    const add = (name: string, price: number, purchase_date: string, lifespan_years: number, tag_id?: string) =>
        call(request, parent, 'POST', '/assets',
            { name, price, purchase_date, lifespan_years, owner_id: me, tag_ids: tag_id ? [tag_id] : [] });
    await add('Auto', 30000, `${nextYear - 5}-06-01`, 10, mobility.id);
    // Replaced in less than a year: the group shows it even when folded
    await add('Velo', 1500, `${nextYear - 5}-01-01`, 5, mobility.id);
    await add('Ski', 720, `${nextYear - 2}-01-01`, 3);
    const errors = await login(page, parent);
    await tab(page, '📦 Investments');

    const group = page.locator('details', { has: page.getByText(`Mobilität ${parent.name}`) });
    const summary = group.locator('summary');
    await expect(summary).toContainText('2 items');
    await expect(summary).toContainText('CHF 275.00 / month');
    await expect(summary).toContainText('due soon');
    await expect(page.locator('details', { has: page.getByText('No tag', { exact: true }) }).locator('summary'))
        .toContainText('CHF 20.00 / month');
    await expect(page.getByTestId('investments-total')).toContainText('CHF 295.00 / month');
    // Inside: the sum of what was paid, and what is replaced next
    await expect(group).toContainText(`Bought for CHF 31'500.00`);
    await expect(group).toContainText(`next replacement ${nextYear} (Velo)`);

    // A group folds
    await summary.click();
    await expect(page.getByRole('heading', { name: 'Auto' })).toBeHidden();
    await summary.click();
    await expect(page.getByRole('heading', { name: 'Auto' })).toBeVisible();

    // A new tag right from the form
    await page.getByRole('button', { name: '+ Add Item' }).click();
    await page.getByLabel('Name', { exact: true }).fill('Rasenmäher');
    await page.getByLabel('Price', { exact: true }).fill('600');
    await page.getByRole('button', { name: '+ New tag…' }).click();
    await page.getByLabel('New tag name').fill(`Garten ${parent.name}`);
    await page.getByRole('button', { name: 'Add Item' }).click();
    await expect(page.locator('details', { has: page.getByText(`Garten ${parent.name}`) }).locator('summary'))
        .toContainText('1 item');

    // Archived: out of the totals, in its own folded section; restored: back
    await page.getByRole('button', { name: 'Archive Auto' }).click();
    await page.getByRole('button', { name: 'Archive', exact: true }).click();
    await expect(summary).toContainText('CHF 25.00 / month');
    const archived = page.locator('details', { has: page.getByText('Archived (1)') });
    await expect(archived.getByRole('heading', { name: 'Auto' })).toBeHidden();
    await archived.locator('summary').click();
    await archived.getByRole('button', { name: 'Restore Auto' }).click();
    await expect(summary).toContainText('CHF 275.00 / month');
    await expect(page.getByText(/Archived \(/)).toHaveCount(0);

    // Settings says which investments a tag is on before it is deleted
    await page.getByRole('button', { name: 'Settings' }).click();
    const tags = page.locator('details', { has: page.getByRole('heading', { name: 'Tags' }) });
    await expect(tags.locator('li', { hasText: `Mobilität ${parent.name}` })).toContainText('on 2 investments');
    expect(errors).toEqual([]);
});

// A bike for getting around and for the hobby: in both groups, counted once in the overall total
test('an investment with two tags', async ({ page, request }) => {
    const parent = await newParent(request);
    const me = (await call(request, parent, 'GET', '/me')).id;
    const mobility = await call(request, parent, 'POST', '/tags', { name: `Mobility ${parent.name}` });
    const bike = await call(request, parent, 'POST', '/tags', { name: `Bike ${parent.name}` });
    // 2400 over 10 years: 20 a month
    await call(request, parent, 'POST', '/assets',
        { name: 'Velo', price: 2400, purchase_date: '2024-10-01', lifespan_years: 10, owner_id: me, tag_ids: [mobility.id] });
    const errors = await login(page, parent);
    await tab(page, '📦 Investments');

    // The second tag from the form
    const card = page.locator('div.rounded-lg', { has: page.getByRole('heading', { name: 'Velo' }) });
    await card.first().getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByLabel(`Tag Mobility ${parent.name}`)).toBeChecked();
    await page.getByLabel(`Tag Bike ${parent.name}`).check({ force: true });
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    for (const name of [`Mobility ${parent.name}`, `Bike ${parent.name}`]) {
        const group = page.locator('details', { has: page.getByText(name, { exact: true }) });
        await expect(group.locator('summary')).toContainText('CHF 20.00 / month');
        await expect(group.getByRole('heading', { name: 'Velo' })).toBeVisible();
    }
    await expect(card).toHaveCount(2);
    await expect(card.first()).toContainText('also in:');
    await expect(page.getByTestId('investments-total')).toContainText('CHF 20.00 / month');
    await expect(page.getByTestId('investments-total')).toContainText('counted once');
    expect(errors).toEqual([]);
});
