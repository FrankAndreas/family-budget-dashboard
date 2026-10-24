import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Two different 1×1 PNGs (black, red): the fake AI ignores the picture and answers with a fixed Migros receipt
// (2026-10-20, CHF 83.40); different pictures, so the two photos are two receipts
const PHOTOS = [
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC',
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC',
].map((data, i) => ({ name: `scan-${i}.png`, mimeType: 'image/png', buffer: Buffer.from(data, 'base64') }));

// A pile of receipts photographed first, then checked one after another (receipt scan)
test('scan a pile of receipts, then check and book them one after another', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Konto', type: 'BANK' });
    const errors = await login(page, parent);

    // The first upload fails once: the photo stays on the screen with a retry
    let failOnce = true;
    await page.route('**/api/v1/inbox/photos', route => {
        if (route.request().method() === 'POST' && failOnce) {
            failOnce = false;
            return route.abort();
        }
        return route.continue();
    });
    await page.getByRole('button', { name: '📷 Scan receipts' }).first().click();
    const camera = page.getByLabel('Receipt photo');
    await camera.setInputFiles(PHOTOS[0]);
    await expect(page.getByText('upload failed')).toBeVisible();
    await camera.setInputFiles(PHOTOS[1]);
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText('✓ in the inbox')).toHaveCount(2);
    // Network errors from the aborted upload are expected in the console
    errors.length = 0;
    await page.getByRole('button', { name: 'Done (2)' }).click();

    const rows = page.getByText('Migros · CHF 83.40');
    await expect(rows).toHaveCount(2);
    await page.getByRole('button', { name: 'Check next' }).click();
    await expect(page.getByText('Sum CHF 83.40')).toBeVisible();
    const booked = async () => (await call(request, parent, 'GET', `/accounts/${account.id}/transactions`)).length;
    await page.getByRole('button', { name: 'Book & next' }).click();
    // The check view shows the next photo straight away, not the list
    await expect.poll(booked).toBe(1);
    await expect(page.getByText('Receipt 1 of 1')).toBeVisible();
    await expect(page.getByText('Sum CHF 83.40')).toBeVisible();
    await page.getByRole('button', { name: 'Book & next' }).click();
    await expect(page.getByRole('button', { name: 'Check next' })).toHaveCount(0);
    await expect(rows).toHaveCount(0);

    const bookings = await call(request, parent, 'GET', `/accounts/${account.id}/transactions`);
    expect(bookings.map((b: { items: unknown[]; attachments: unknown[] }) => [b.items.length, b.attachments.length]))
        .toEqual([[2, 1], [2, 1]]);
    expect(errors).toEqual([]);
});
