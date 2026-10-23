import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Invented IBAN (also in converter.example.toml) and texts: the repository is public
const IBAN = 'CH93 0076 2011 6238 5295 7';
const HEADER = 'IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date';
const row = (text: string, amount: string, saldo: string) =>
    `CH9300762011623852957;2026-09-01 00:00:00.0;${text};${amount};${saldo};2026-09-01 00:00:00.0`;

// The Raiffeisen CSV uploaded as it is: the account by IBAN, categories by preset rule, own rule and the (fake) AI
test('bank statement upload', async ({ page, request }, testInfo) => {
    const parent = await newParent(request);
    const errors = await login(page, parent);

    await page.getByRole('button', { name: '+ Add Account' }).click();
    await page.getByPlaceholder('Account Name').fill('Raiffeisen');
    await page.getByLabel('IBAN').fill(IBAN.toLowerCase());
    await page.getByRole('button', { name: 'Create Account' }).click();
    await expect(page.getByText(IBAN)).toBeVisible();

    await page.getByRole('button', { name: 'Settings' }).click();
    // A new database starts with the suggested rules; the button adds only what is missing
    await expect(page.getByText('DOSENBACH SPORT → Sport')).toBeVisible();
    await page.getByRole('button', { name: 'Add suggested rules (Swiss shops)' }).click();
    await expect(page.getByText('0 rules and 0 new categories added.')).toBeVisible();

    // Rules are family-wide and other tests share the database: a text of this test's own
    const employer = `Arbeit ${parent.name}`;
    await page.getByLabel('Text', { exact: true }).fill(employer);
    await page.getByLabel('Category', { exact: true }).selectOption({ label: 'Salary' });
    await page.getByRole('button', { name: 'Add rule' }).click();
    await expect(page.getByText(`${employer} → Salary`)).toBeVisible();

    const file = testInfo.outputPath('export.csv');
    fs.writeFileSync(file, [
        HEADER,
        row('Einkauf TWINT Coop Stans', '-20.00', '980.00'),
        row(`Gutschrift ${employer}`, '5000', '5980.00'),
        row('Einkauf Kiosk Beispiel', '-3.50', '5976.50'),
        row('Zinsabschluss', '0.0', '5976.50'),
    ].join('\n') + '\n');
    await page.getByLabel('File to import').setInputFiles(file);
    await expect(page.getByText('by rule: COOP')).toBeVisible();
    await expect(page.getByLabel('Category of line 2')).toHaveValue('Groceries');
    await expect(page.getByText(`by rule: ${employer}`)).toBeVisible();
    await expect(page.getByText('AI suggestion')).toBeVisible();
    await expect(page.getByLabel('Category of line 4')).toHaveValue('Groceries');
    await expect(page.getByText('Amount 0, not booked')).toBeVisible();
    await expect(page.getByText('bank CHF 5\'976.50 · app after the import CHF 4\'976.50')).toBeVisible();

    await page.getByRole('button', { name: 'Import 3 transactions' }).click();
    await expect(page.getByText('Imported 3 transactions')).toBeVisible();
    const accounts = await call(request, parent, 'GET', '/accounts');
    expect(accounts.find((a: { name: string }) => a.name === 'Raiffeisen').balance).toBe(4976.5);
    expect(errors).toEqual([]);
});
