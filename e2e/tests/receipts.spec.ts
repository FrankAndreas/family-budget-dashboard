import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// A 1×1 white PNG: the fake AI ignores the picture and answers with a fixed Migros receipt
const PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC', 'base64');

// Receipt → items with tags → one booking (issue #56): an item with two tags counts in full in both
test('read a receipt, tag an item twice, and see it in analytics and a tag budget', async ({ page, request }) => {
    const parent = await newParent(request);
    await call(request, parent, 'POST', '/accounts', { name: 'Migros', type: 'CLEARING' });
    // Tags are family-wide and the test database is shared: names of their own
    const velo = await call(request, parent, 'POST', '/tags', { name: `Velo ${parent.name}`, icon: '🚲' });
    const sport = await call(request, parent, 'POST', '/tags', { name: `Sport ${parent.name}` });
    await call(request, parent, 'POST', '/budgets', { tag_id: velo.id, limit: 4000, period: 'YEARLY' });

    const errors = await login(page, parent);
    await page.getByRole('button', { name: '📷 Receipt' }).click();
    await page.getByLabel('Receipt file').setInputFiles({ name: 'beleg.png', mimeType: 'image/png', buffer: PNG });
    await expect(page.getByLabel('Name of item 2')).toHaveValue('Velo-Hose');
    await expect(page.getByLabel('Amount of item 1')).toHaveValue('3.50');
    await expect(page.getByText('Sum CHF 83.40')).toBeVisible();

    // Book it today, so it lands in this month and year whenever the test runs
    const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Zurich' }).format(new Date());
    await page.getByLabel('Date').fill(today);
    // The chip around the visually hidden checkbox: a forced click on the box itself can land elsewhere
    await page.locator('label', { has: page.getByLabel(`Tag ${velo.name} for item 2`) }).click();
    await expect(page.getByLabel(`Tag ${velo.name} for item 2`)).toBeChecked();
    // The chip around the visually hidden checkbox: a forced click on the box itself can land elsewhere
    await page.locator('label', { has: page.getByLabel(`Tag ${sport.name} for item 2`) }).click();
    await expect(page.getByLabel(`Tag ${sport.name} for item 2`)).toBeChecked();
    await page.getByRole('button', { name: 'Book', exact: true }).click();

    const items = page.getByRole('button', { name: /2 items/ });
    await expect(items).toBeVisible();
    await expect(items).toContainText('📎 1');
    await items.click();
    await expect(page.getByText('Velo-Hose')).toBeVisible();

    await page.getByRole('button', { name: 'Analytics' }).click();
    const byTag = page.locator('.glass-card', { has: page.getByRole('heading', { name: /Spending by Tag/ }) });
    await expect(byTag.locator('div', { hasText: velo.name }).last()).toContainText('CHF 79.90');
    await expect(byTag.locator('div', { hasText: sport.name }).last()).toContainText('CHF 79.90');

    await page.getByRole('button', { name: 'Budgets' }).click();
    await expect(page.getByText("CHF 79.90 / CHF 4'000.00")).toBeVisible();
    expect(errors).toEqual([]);
});
