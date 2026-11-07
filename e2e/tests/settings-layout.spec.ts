import { expect, test } from '@playwright/test';
import { addToHub, login, newParent, tab } from './helpers';

// UX review 2026-11-07: the Common tab only once there is a second parent; the import and article rules in their
// own Settings section next to the categories; Privacy & Security only with what applies to the family
test('a parent on their own: no Common tab, rules next to the categories, no privacy filler', async ({ page, request }) => {
    const parent = await newParent(request);
    // The browser tests share one family with many parents: here the family is only this parent
    await page.route('**/api/v1/users', async route => {
        const response = await route.fetch();
        const users: { username: string }[] = await response.json();
        await route.fulfill({ response, json: users.filter(u => u.username === parent.name) });
    });
    const errors = await login(page, parent);

    await expect(page.getByRole('button', { name: '📦 Investments' })).toBeVisible();
    await expect(page.getByRole('button', { name: '🤝 Common' })).toHaveCount(0);

    await tab(page, '⚙️ Settings');
    const headings = await page.locator('details > summary h2').allInnerTexts();
    expect(headings.indexOf('Category rules')).toBe(headings.indexOf('Tags') + 1);
    expect(headings.indexOf('Category rules')).toBeLessThan(headings.indexOf('Data Management'));
    const rules = page.locator('details', { hasText: 'Category rules' });
    await expect(rules.getByText('Article rules (Migros receipts)')).toBeVisible();
    await expect(rules.getByLabel('Search rules')).toBeVisible();
    const data = page.locator('details', { has: page.getByRole('heading', { name: 'Data Management' }) });
    await expect(data.getByLabel('Search rules')).toHaveCount(0);
    // Nothing to say about privacy for a parent on their own
    await expect(page.getByText('Data Retention')).toHaveCount(0);
    await expect(page.getByText('Privacy & Security')).toHaveCount(0);
    expect(errors).toEqual([]);
});

test('with a second parent the Common tab and the sharing rules appear', async ({ page, request }) => {
    const parent = await newParent(request);
    await addToHub(request, `${parent.name}b`, 'PARENT');
    const errors = await login(page, parent);

    await tab(page, '🤝 Common');
    await expect(page.getByRole('heading', { name: 'Common budget' })).toBeVisible();
    await tab(page, '⚙️ Settings');
    await expect(page.getByText('Privacy & Security')).toBeVisible();
    await expect(page.getByText('The Common tab (shared costs and settling up) is visible to both parents')).toBeVisible();
    // Only children with their own money have privacy mode
    await expect(page.getByText(/privacy mode/)).toHaveCount(0);
    expect(errors).toEqual([]);
});
