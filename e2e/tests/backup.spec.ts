import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// The JSON backup holds the user's own accounts only, not those another parent shared for viewing (#17)
test('backup leaves out view-only shared accounts', async ({ page, request }) => {
    const mum = await newParent(request);
    const dad = await newParent(request);
    const mine = await call(request, mum, 'POST', '/accounts', { name: 'Mum bank', type: 'BANK' });
    const dads = await call(request, dad, 'POST', '/accounts', { name: 'Dad bank', type: 'BANK' });
    const categories = await call(request, mum, 'GET', '/categories');
    const gift = categories.find((c: { name: string }) => c.name === 'Gift').id;
    await call(request, mum, 'POST', '/transactions', { account_id: mine.id, category_id: gift, amount: 10 });
    await call(request, dad, 'POST', '/transactions', { account_id: dads.id, category_id: gift, amount: 20 });
    const mumId = (await call(request, mum, 'GET', '/me')).id;
    await call(request, dad, 'PUT', `/shares/${mumId}`, { level: 'VIEW' });
    expect((await call(request, mum, 'GET', '/accounts')).map((a: { name: string }) => a.name).sort()).toEqual(['Dad bank', 'Mum bank']);

    const errors = await login(page, mum);
    await page.getByRole('button', { name: 'Settings' }).click();
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: /Backup \(JSON\)/ }).click();
    const backup = JSON.parse(fs.readFileSync(await (await download).path(), 'utf-8'));
    expect(backup.accounts.map((a: { name: string }) => a.name)).toEqual(['Mum bank']);
    expect(backup.transactions.map((t: { amount: number }) => t.amount)).toEqual([10]);
    expect(errors).toEqual([]);
});
