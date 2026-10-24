import { expect, test } from '@playwright/test';
import { API, call, login, newParent } from './helpers';

// Invented IBAN and text (the repository is public); an IBAN of this test's own, the database is shared
const IBAN = 'CH9100762000000000001';
const HEADER = 'IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date';
// A 1×1 white PNG: the fake AI ignores the picture and answers with a fixed Migros receipt (2026-10-20, CHF 83.40)
const PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC', 'base64');

// A receipt that comes after the statement goes onto the bank booking that paid it, instead of a second booking
test('receipt put onto the bank booking that paid it', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Konto', type: 'BANK', iban: IBAN });
    const statement = `${HEADER}\n${IBAN};2026-10-21 00:00:00.0;Einkauf TWINT Muster Laden;-83.40;916.60;2026-10-21 00:00:00.0\n`;
    const imported = await request.post(`${API}/import`, {
        headers: { Authorization: `Bearer ${parent.token}` },
        multipart: { file: { name: 'statement.csv', mimeType: 'text/csv', buffer: Buffer.from(statement) } },
    });
    expect(imported.ok(), await imported.text()).toBeTruthy();
    const [payment] = await call(request, parent, 'GET', `/accounts/${account.id}/transactions`);

    const errors = await login(page, parent);
    await page.getByRole('button', { name: '📷 Receipt' }).click();
    await page.getByLabel('Receipt file').setInputFiles({ name: 'beleg.png', mimeType: 'image/png', buffer: PNG });
    await expect(page.getByText('Sum CHF 83.40')).toBeVisible();
    const onto = page.getByLabel('Paid with this bank booking');
    await expect(onto).toHaveValue('');
    await expect(onto.locator('option')).toHaveText(['none: a new booking', /Einkauf TWINT Muster Laden · 2026-10-21/]);
    await onto.selectOption(payment.id);
    await page.getByRole('button', { name: 'Book', exact: true }).click();

    // Still one booking: the bank's, now with the receipt's items and still confirmed
    await expect(page.getByRole('button', { name: /2 items.*1 bank line/ })).toBeVisible();
    await expect(page.getByText('not confirmed')).toHaveCount(0);
    const bookings = await call(request, parent, 'GET', `/accounts/${account.id}/transactions`);
    expect(bookings.map((b: { id: string; items: unknown[] }) => [b.id, b.items.length])).toEqual([[payment.id, 2]]);
    expect(errors).toEqual([]);
});
