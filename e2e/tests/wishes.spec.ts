import { expect, test, type Page } from '@playwright/test';
import { login, newParent } from './helpers';

const names = (page: Page, selector: string) => page.locator(selector).allTextContents();

// Wishes tab: add, reorder, family plan with a running total, search links, bought, best price
test('wish lists and the family plan', async ({ page, request }) => {
    const parent = await newParent(request);
    const errors = await login(page, parent);
    await page.getByRole('button', { name: 'Wishes' }).click();

    for (const [name, estimate] of [['Bike', '800'], ['Lamp', '120'], ['Tent', '300']]) {
        await page.getByRole('button', { name: '+ Add wish' }).click();
        await page.getByLabel('Wish name').fill(name);
        await page.getByLabel('Estimate').fill(estimate);
        await page.getByRole('button', { name: 'Save wish' }).click();
        await expect(page.locator('[data-wish-name]', { hasText: name })).toBeVisible();
    }
    expect(await names(page, '[data-wish-name]')).toEqual(['Bike', 'Lamp', 'Tent']);
    await page.getByRole('button', { name: 'Move Tent up' }).click();
    await expect.poll(() => names(page, '[data-wish-name]')).toEqual(['Bike', 'Tent', 'Lamp']);
    await expect(page.getByText('Total $1220.00')).toBeVisible();

    await page.getByRole('button', { name: 'Add Bike to the family plan' }).click();
    await page.getByRole('button', { name: 'Add Lamp to the family plan' }).click();
    await expect(page.getByRole('button', { name: 'Remove Lamp from the family plan' })).toBeVisible();
    await page.getByRole('button', { name: 'Family plan', exact: true }).click();
    await expect.poll(() => names(page, '[data-plan-name]')).toEqual(['Bike', 'Lamp']);
    expect(await names(page, '[data-plan-total]')).toEqual(['$800.00', '$920.00']);
    await page.getByRole('button', { name: 'Move Lamp up in the family plan' }).click();
    await expect.poll(() => names(page, '[data-plan-name]')).toEqual(['Lamp', 'Bike']);

    await page.getByRole('button', { name: 'My lists', exact: true }).click();
    await page.getByRole('button', { name: 'Search Bike' }).click();
    const links = await page.locator('a[data-search]').evaluateAll(as => as.map(a => (a as HTMLAnchorElement).href));
    expect(links).toEqual([
        'https://www.toppreise.ch/produktsuche?q=Bike',
        'https://www.galaxus.ch/de/search?q=Bike',
        'https://www.google.com/search?udm=28&q=Bike',
    ]);

    await page.getByRole('button', { name: 'Mark Tent as bought' }).click();
    await expect.poll(() => names(page, '[data-wish-name]')).toEqual(['Bike', 'Lamp']);
    await expect(page.getByText('Bought (1)')).toBeVisible();

    // The best price found replaces the estimate in the price
    await page.getByRole('button', { name: 'Edit Lamp' }).click();
    await page.getByLabel('Best price').fill('99.50');
    await page.getByLabel('Shop').fill('Shop A');
    await page.getByRole('button', { name: 'Save wish' }).click();
    await expect(page.getByText('best $99.50 at Shop A')).toBeVisible();
    expect(errors).toEqual([]);
});
