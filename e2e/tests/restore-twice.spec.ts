import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { answerConfirmsYourself, appConfirm, call, login, newParent, tab } from './helpers';

// UX review 2026-11-07: restoring the same backup again adds nothing twice; what is missing comes back
test('a backup restored twice adds nothing twice', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const category = (name: string) => categories.find((c: { name: string }) => c.name === name).id;
    // Two equal coffees on the same day stay two
    for (const [name, amount, description] of [['Dining Out', 4.5, 'Kaffee'], ['Dining Out', 4.5, 'Kaffee'], ['Rent', 1800, 'Miete']] as const) {
        await call(request, parent, 'POST', '/transactions',
            { account_id: account.id, category_id: category(name), amount, description, date: '2026-10-05T08:00:00Z' });
    }
    await call(request, parent, 'POST', '/budgets', { category_id: category('Dining Out'), limit: 100, period: 'MONTHLY' });
    const errors = await login(page, parent);
    await tab(page, '⚙️ Settings');
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: /Backup \(JSON\)/ }).click();
    const file = await (await download).path();
    expect(JSON.parse(fs.readFileSync(file, 'utf-8')).transactions).toHaveLength(3);

    const restore = page.getByLabel('Backup file to restore');
    await restore.setInputFiles(file);
    await expect(page.getByText('Imported 0 budgets and transactions. 4 were already there and were skipped.')).toBeVisible();
    const bookings = () => call(request, parent, 'GET', `/accounts/${account.id}/transactions`);
    expect(await bookings()).toHaveLength(3);
    expect(await call(request, parent, 'GET', '/accounts')).toHaveLength(1);
    expect(await call(request, parent, 'GET', '/budgets')).toHaveLength(1);

    // One coffee lost: only that one comes back
    const coffee = (await bookings()).find((b: { description: string }) => b.description === 'Kaffee');
    await call(request, parent, 'DELETE', `/transactions/${coffee.id}`);
    await restore.setInputFiles(file);
    await expect(page.getByText('Imported 1 budgets and transactions. 3 were already there and were skipped.')).toBeVisible();
    expect((await bookings()).filter((b: { description: string }) => b.description === 'Kaffee')).toHaveLength(2);
    expect(errors).toEqual([]);
});

// The app's own question instead of the browser's: says what goes with the account, Cancel keeps it
test('deleting an account asks in the app, with its bookings', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Sparkonto', type: 'SAVINGS' });
    const categories = await call(request, parent, 'GET', '/categories');
    const gift = categories.find((c: { name: string }) => c.name === 'Gift').id;
    for (const amount of [10, 20]) {
        await call(request, parent, 'POST', '/transactions', { account_id: account.id, category_id: gift, amount });
    }
    const errors = await login(page, parent);
    await answerConfirmsYourself(page);
    const card = page.locator('.cursor-pointer', { hasText: 'Sparkonto' });

    await card.getByRole('button', { name: 'Delete' }).click();
    await expect(appConfirm(page)).toContainText('Delete the account "Sparkonto" with its 2 bookings? This cannot be undone.');
    await page.keyboard.press('Escape');
    await expect(appConfirm(page)).toHaveCount(0);
    await expect(card).toBeVisible();

    await card.getByRole('button', { name: 'Delete' }).click();
    await appConfirm(page).getByRole('button', { name: 'Delete' }).click();
    await expect(card).toHaveCount(0);
    expect(await call(request, parent, 'GET', '/accounts')).toEqual([]);
    expect(errors).toEqual([]);
});
