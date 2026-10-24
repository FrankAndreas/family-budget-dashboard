import { expect, test } from '@playwright/test';
import { API, call, login, newParent } from './helpers';

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
    // Each row has a thumbnail and the app's date format; the fake AI reads both as the same receipt, so the later
    // one is flagged (earlier tests' photos read the same, so the first may be flagged too)
    await expect(page.getByRole('img', { name: 'Photo 2' })).toBeVisible();
    await expect(page.getByText(/photographed by .* · \d{1,2} [A-Z][a-z]{2} \d{4}, \d\d:\d\d/)).toHaveCount(2);
    await expect(page.getByText('possibly a duplicate').last()).toBeVisible();
    await page.getByRole('button', { name: 'Check next' }).click();
    await expect(page.getByText('Sum CHF 83.40')).toBeVisible();
    // The photo is shown to check the reading against; no file to choose, the photo is already attached
    await expect(page.getByRole('img', { name: 'Photo of the receipt' })).toBeVisible();
    await expect(page.getByLabel('Receipt file')).toHaveCount(0);
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

// A photo the browser can't decode is never dropped silently: it shows as failed, so the paper isn't thrown away
test('a photo that cannot be read shows as failed', async ({ page, request }) => {
    const parent = await newParent(request);
    await call(request, parent, 'POST', '/accounts', { name: 'Konto', type: 'BANK' });
    await login(page, parent);
    await page.getByRole('button', { name: '📷 Scan receipts' }).first().click();
    await page.getByLabel('Receipt photo').setInputFiles({
        name: 'broken.png', mimeType: 'image/png', buffer: Buffer.from('not a picture'),
    });
    await expect(page.getByText('upload failed')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
});

// "Read with AI" off: the photos are never sent to the AI and are typed in when checked
test('a pile scanned without the AI is typed in', async ({ page, request }) => {
    const parent = await newParent(request);
    await call(request, parent, 'POST', '/accounts', { name: 'Konto', type: 'BANK' });
    const errors = await login(page, parent);
    await page.getByRole('button', { name: '📷 Scan receipts' }).first().click();
    await page.getByLabel('Read with AI').uncheck();
    await page.getByLabel('Receipt photo').setInputFiles(PHOTOS[0]);
    await expect(page.getByText('✓ in the inbox')).toHaveCount(1);
    await page.getByRole('button', { name: 'Done (1)' }).click();

    await expect(page.getByText('without AI: type it in')).toBeVisible();
    await page.getByRole('button', { name: 'Check next' }).click();
    await expect(page.getByRole('img', { name: 'Photo of the receipt' })).toBeVisible();
    await expect(page.getByText('Sum CHF 0.00')).toBeVisible();
    const [photo] = await call(request, parent, 'GET', '/inbox/photos');
    expect(photo.read_state).toBe('manual');
    expect(errors).toEqual([]);
});

// The other parent's photo, when their accounts aren't shared for booking: the row says why no account is chosen
test("the other parent's photo explains the missing account", async ({ page, request }) => {
    const parent = await newParent(request);
    const other = await newParent(request);
    await call(request, parent, 'POST', '/accounts', { name: 'Konto', type: 'BANK' });
    const uploaded = await request.post(`${API}/inbox/photos`, {
        multipart: { file: PHOTOS[0] },
        headers: { Authorization: `Bearer ${other.token}` },
    });
    expect(uploaded.ok(), await uploaded.text()).toBeTruthy();
    const photo = await uploaded.json();
    const errors = await login(page, parent);
    await expect(page.getByText(`${other.name}'s accounts aren't shared with you for booking`)).toBeVisible();
    // Left as it was: the other tests count the Migros rows
    await call(request, other, 'DELETE', `/inbox/photos/${photo.id}`);
    expect(errors).toEqual([]);
});
