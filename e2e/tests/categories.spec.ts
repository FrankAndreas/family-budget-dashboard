import { expect, test } from '@playwright/test';
import { login, newParent } from './helpers';

// Settings → Categories: add, rename and delete a category; system categories are locked
test('manage categories in Settings', async ({ page, request }) => {
    const parent = await newParent(request);
    const errors = await login(page, parent);
    await page.getByRole('button', { name: 'Settings' }).click();
    const section = page.locator('details', { has: page.getByRole('heading', { name: 'Categories' }) });

    // Unique name: categories are family-wide, and other tests share the database
    const name = `Leasing ${parent.name}`;
    await section.getByLabel('New category name').fill(name);
    await section.getByLabel('New category type').selectOption('EXPENSE');
    await section.getByLabel('New category icon').fill('🚙');
    await section.getByRole('button', { name: 'Add category' }).click();
    const row = section.locator('li', { hasText: name });
    await expect(row).toContainText('🚙');

    await row.getByRole('button', { name: 'Edit' }).click();
    await section.getByLabel(`Name of ${name}`).fill(`${name} car`);
    await section.getByRole('button', { name: 'Save' }).click();
    const renamed = section.locator('li', { hasText: `${name} car` });
    await expect(renamed).toBeVisible();

    await renamed.getByRole('button', { name: 'Delete' }).click();
    await expect(section.locator('li', { hasText: name })).toHaveCount(0);

    const unsorted = section.locator('li', { hasText: 'Unsorted' });
    await expect(unsorted).toContainText('🔒');
    await expect(unsorted.getByRole('button', { name: 'Delete' })).toHaveCount(0);
    expect(errors).toEqual([]);
});
