import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import { call, login, newParent, PYTHON } from './helpers';

const REPO = path.resolve(__dirname, '..', '..');
// An example IBAN (invented data only: the repository is public)
const IBAN = 'CH9300762011623852957';

// Bank converter output imported through the preview; transfers show their direction and can be deleted
test('converted bank export with a transfer to the Migros account', async ({ page, request }, testInfo) => {
    const parent = await newParent(request);
    const household = await call(request, parent, 'POST', '/accounts', { name: 'Household', type: 'BANK' });
    const migros = await call(request, parent, 'POST', '/accounts', { name: 'Migros', type: 'CLEARING' });

    const dir = testInfo.outputPath('converter');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(`${dir}/schema.json`, JSON.stringify(await call(request, parent, 'GET', '/import/schema')));
    fs.writeFileSync(`${dir}/converter.toml`, [
        '[bank.accounts]', `"${IBAN}" = { account = "Household" }`,
        '[[bank.rules]]', "match = 'MIGROS'", 'action = "transfer"', 'to_account = "Migros"', 'description = "Migros"', '',
    ].join('\n'));
    fs.writeFileSync(`${dir}/bank.csv`, [
        'IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date',
        `${IBAN};2026-09-01 00:00:00.0;Gutschrift ACME AG;100.0;100.0;2026-09-01 00:00:00.0`,
        `${IBAN};2026-09-02 00:00:00.0;Einkauf TWINT MIGROS MM BEISPIEL;-34.25;65.75;2026-09-02 00:00:00.0`,
        '',
    ].join('\n'));
    execFileSync(PYTHON, [
        `${REPO}/tools/converters/bank.py`, `${dir}/bank.csv`, '--config', `${dir}/converter.toml`, '--schema', `${dir}/schema.json`,
    ]);

    const errors = await login(page, parent);
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByLabel('File to import').setInputFiles(`${dir}/bank-import.csv`);
    await expect(page.getByText('3 ready')).toBeVisible();
    await expect(page.getByText('← out')).toBeVisible();
    await expect(page.getByText('→ in')).toBeVisible();
    await page.getByRole('button', { name: 'Import 3 transactions' }).click();
    await expect(page.getByText('Imported 3 transactions')).toBeVisible();

    const balance = async (id: string) =>
        (await call(request, parent, 'GET', '/accounts')).find((a: { id: string }) => a.id === id).balance;
    expect(await balance(household.id)).toBe(65.75);
    expect(await balance(migros.id)).toBe(34.25);

    // The transfer on the Migros account: delete yes, edit no
    await page.getByRole('button', { name: 'Accounts' }).first().click();
    await page.locator('.cursor-pointer', { hasText: 'Migros' }).click();
    await expect(page.getByRole('button', { name: 'Delete transaction' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Edit transaction' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Delete transaction' }).click();
    await expect.poll(() => balance(migros.id)).toBe(0);
    expect(await balance(household.id)).toBe(65.75);
    expect(errors).toEqual([]);
});
