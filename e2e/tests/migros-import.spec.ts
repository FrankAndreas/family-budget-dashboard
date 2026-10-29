import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { API, call, login, newParent } from './helpers';

// Invented IBAN (not used by the other specs: IBANs are unique and the database is shared), stores and articles: the
// repository is public
const IBAN = 'CH6400762000000000002';
const BANK_HEADER = 'IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date';
const MIGROS_HEADER = 'Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz';

// The Cumulus export uploaded as it is: the receipt goes onto its TWINT payment, articles by the (fake) AI or a
// change, which become article rules; the same file again is recognised
test('the Migros export is imported onto its payment', async ({ page, request }, testInfo) => {
    const parent = await newParent(request);
    // Article rules are family-wide and the browser tests share a database: names of this test's own
    const brot = `Brot ${parent.name}`;
    const zahnpasta = `Zahnpasta ${parent.name}`;
    const karotten = `Karotten ${parent.name}`;
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK', iban: IBAN });
    const statement = await request.post(`${API}/import`, {
        multipart: {
            file: {
                name: 'export.csv', mimeType: 'text/csv',
                buffer: Buffer.from(`${BANK_HEADER}\n${IBAN};2026-09-13 00:00:00.0;Einkauf TWINT Migros;-7.40;992.60;2026-09-13 00:00:00.0\n`),
            },
        },
        headers: { Authorization: `Bearer ${parent.token}` },
    });
    expect(statement.ok(), await statement.text()).toBeTruthy();
    const errors = await login(page, parent);

    // Brot 3.50 + Zahnpasta 6.95 + Karotten 3.90 − 3.90 + 1.95 − voucher 5.00 = 7.40; points only: dropped
    const first = '12.09.2026;11:35:25;Filiale Muster;270;133';
    const second = '20.09.2026;17:02:00;Beispiel Markt;004;10';
    const file = testInfo.outputPath('kassenbeleg.csv');
    fs.writeFileSync(file, [
        MIGROS_HEADER,
        `${first};${brot};1;0.00;3.50`,
        `${first};${zahnpasta};1;0.00;6.95`,
        `${first};${karotten};2;0.00;3.90`,
        `${first};${karotten};-2;0.00;-3.90`,
        `${first};${karotten};1;0.00;1.95`,
        `${first};CUMULUS BON 5.-;0;0;-5.00`,
        `${first};Bonus-Coupon 2x;1;0;0`,
        `${second};${brot};1;0.00;3.50`,
    ].join('\n') + '\n');

    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByLabel('File to import').setInputFiles(file);
    await expect(page.getByLabel('Payment for receipt 12.09.2026 Filiale Muster')).toContainText('CHF 7.40');
    await expect(page.getByLabel('Account for receipt 20.09.2026 Beispiel Markt')).toHaveValue(account.id);
    await page.getByText('Filiale Muster').click();
    await expect(page.getByLabel(`Category of ${zahnpasta}`)).toHaveValue(/.+/);
    await expect(page.getByLabel(`Category of ${zahnpasta}`).locator('option:checked')).toHaveText('Healthcare');
    await expect(page.locator('li li', { hasText: zahnpasta }).getByText('AI suggestion')).toBeVisible();
    // The preview fits a phone
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    // The open receipt's line: the other receipt (folded) has Brot too, and a change applies to both
    const opened = page.locator('li', { hasText: 'Filiale Muster' }).first();
    await opened.getByLabel(`Category of ${brot}`).selectOption({ label: 'Other Expense' });
    // Brot changed, Zahnpasta and Karotten by the AI
    await expect(page.getByText('3 new article rules')).toBeVisible();

    await page.getByRole('button', { name: 'Import 2 receipts' }).click();
    await expect(page.getByText('1 onto payments, 1 booked new, 3 new article rules')).toBeVisible();
    const bookings: { description: string; items: { name: string }[] }[] =
        await call(request, parent, 'GET', `/accounts/${account.id}/transactions`);
    const paid = bookings.find(b => b.description === 'Migros Filiale Muster');
    expect(paid?.items.map(i => i.name)).toEqual([brot, zahnpasta, karotten, 'CUMULUS BON 5.-']);
    expect(bookings).toHaveLength(2);

    await page.getByLabel('Search article rules').fill(parent.name);
    await expect(page.getByText(`${brot} → Other Expense`)).toBeVisible();
    await expect(page.getByText(`${zahnpasta} → Healthcare`)).toBeVisible();
    await expect(page.getByRole('button', { name: `Edit the rule for ${brot}` })).toBeVisible();
    await expect(page.getByRole('button', { name: `Delete the rule for ${brot}` })).toBeVisible();

    // The same file again: nothing to import
    await page.getByLabel('File to import').setInputFiles(file);
    await expect(page.getByText('already imported')).toHaveCount(2);
    await expect(page.getByRole('button', { name: 'Import 0 receipts' })).toBeDisabled();
    expect(errors).toEqual([]);
});
