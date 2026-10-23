import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Invented IBAN and texts (the repository is public); another IBAN than bank-import.spec.ts, the database is shared
const IBAN = 'CH5604835012345678009';
const HEADER = 'IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date';
const row = (day: string, text: string, amount: string) =>
    `${IBAN};${day} 00:00:00.0;${text};${amount};1000.00;${day} 00:00:00.0`;

// A receipt typed in before the statement is confirmed by its bank line; what is left shows as open points
test('receipt confirmed by the bank statement', async ({ page, request }, testInfo) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Konto', type: 'BANK', iban: IBAN });
    const categories = await call(request, parent, 'GET', '/categories');
    const groceries = categories.find((c: { name: string }) => c.name === 'Groceries').id;
    const receipt = await call(request, parent, 'POST', '/transactions', {
        account_id: account.id, date: '2026-09-03T12:00:00Z', description: 'Muster Laden',
        items: [{ name: 'Brot', amount: 50, category_id: groceries }, { name: 'Käse', amount: 34.3, category_id: groceries }],
    });
    await call(request, parent, 'POST', '/transactions', {
        account_id: account.id, date: '2026-09-01T12:00:00Z', description: 'Kiosk', amount: 10, category_id: groceries,
    });
    // Rules are family-wide: a text of this test's own
    const shop = `Laden ${parent.name}`;
    await call(request, parent, 'POST', '/import/rules', { text: shop, category_id: groceries, receipt_expected: true });

    const errors = await login(page, parent);
    // No statement imported yet: no badges
    await expect(page.getByText('Muster Laden')).toBeVisible();
    await expect(page.getByText('not confirmed')).toHaveCount(0);

    const file = testInfo.outputPath('statement.csv');
    fs.writeFileSync(file, [
        HEADER,
        row('2026-09-05', 'Einkauf TWINT Muster Laden', '-84.30'),
        row('2026-09-20', `Einkauf TWINT ${shop}`, '-20.00'),
    ].join('\n') + '\n');
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByLabel('File to import').setInputFiles(file);
    await expect(page.getByLabel('Booking that line 2 confirms')).toHaveValue(receipt.id);
    await page.getByRole('button', { name: 'Import 2 transactions' }).click();
    await expect(page.getByText('Imported 2 transactions')).toBeVisible();

    await page.getByRole('button', { name: 'Accounts' }).first().click();
    await expect(page.getByText('no payment found')).toBeVisible();
    await expect(page.getByText('receipt missing')).toBeVisible();
    // The receipt is confirmed: it shows its bank line when opened
    await page.getByRole('button', { name: /2 items.*1 bank line/ }).click();
    await expect(page.getByText('Einkauf TWINT Muster Laden')).toBeVisible();

    await page.getByRole('button', { name: '2 open points' }).first().click();
    await expect(page.getByText('Kiosk')).toBeVisible();
    await expect(page.getByText('Muster Laden')).toHaveCount(0);
    expect(errors).toEqual([]);
});
