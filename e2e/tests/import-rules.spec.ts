import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

const HEADER = 'date,account,category,amount,direction,description,reference';

// Import preview: change a category and remember it; the next import uses the rule; Settings lists it
test('category changed in the preview becomes an import rule', async ({ page, request }, testInfo) => {
    const parent = await newParent(request);
    await call(request, parent, 'POST', '/accounts', { name: 'Bank', type: 'BANK' });
    // Unique text: rules are family-wide, and other tests share the database
    const shop = `Bäckerei ${parent.name}`;
    const first = testInfo.outputPath('first.csv');
    const second = testInfo.outputPath('second.csv');
    fs.writeFileSync(first, `${HEADER}\n2026-09-06,Bank,Unsorted,22.10,,${shop} Dorf,${parent.name}:1\n2026-09-07,Bank,Groceries,5.00,,Kiosk,${parent.name}:3\n`);
    fs.writeFileSync(second, `${HEADER}\n2026-10-01,Bank,Unsorted,8.00,,${shop.toUpperCase()} Bahnhof,${parent.name}:2\n`);

    const errors = await login(page, parent);
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByLabel('File to import').setInputFiles(first);
    const category = page.getByLabel('Category of line 2');
    const options = await category.locator('option').allTextContents();
    expect(options).toContain('Groceries');
    expect(options).toContain('Transfer (out)');
    expect(options).not.toContain('Salary');

    await category.selectOption('Groceries');
    await expect(page.locator('s', { hasText: 'Unsorted' })).toBeVisible();
    await page.getByLabel('Remember line 2 as a rule').check();
    await page.getByLabel('Rule text for line 2').fill(shop);
    await page.getByRole('button', { name: 'Import 2 transactions' }).click();
    await expect(page.getByText('Imported 2 transactions')).toBeVisible();
    await expect(page.getByText(`${shop} → Groceries`)).toBeVisible();

    const rule = page.locator('li', { hasText: `${shop} → Groceries` });
    await rule.getByRole('button', { name: 'Show for converter.toml' }).click();
    await expect(rule.locator('pre')).toContainText(`category = "Groceries"`);

    await page.getByLabel('File to import').setInputFiles(second);
    await expect(page.getByText(`by rule: ${shop}`)).toBeVisible();
    await expect(page.getByLabel('Category of line 2')).toHaveValue('Groceries');

    const schema = await call(request, parent, 'GET', '/import/schema');
    expect(schema['x-rules']).toContainEqual({ contains: shop, category: 'Groceries' });
    expect(errors).toEqual([]);
});
