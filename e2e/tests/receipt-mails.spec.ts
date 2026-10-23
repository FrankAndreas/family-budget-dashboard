import { expect, test } from '@playwright/test';
import { API, call, login, newParent, tab } from './helpers';

// A forwarded receipt mail (issue #57), made up here: it names a test address, never a real one
function mail(from: string): string {
    return [
        `From: ${from}`,
        'To: invoice@example.ch',
        'Subject: WG: Ihre Bestellung',
        'Date: Thu, 22 Oct 2026 18:30:00 +0200',
        `Message-ID: <${Date.now()}@example.ch>`,
        'Content-Type: text/plain; charset=utf-8',
        '',
        'Brot 3.50, Velo-Hose 79.90, Total CHF 83.40',
        '',
    ].join('\r\n');
}

test('a forwarded receipt mail is released, read and booked', async ({ page, request }) => {
    const parent = await newParent(request);
    await call(request, parent, 'POST', '/accounts', { name: 'Migros', type: 'CLEARING' });
    const address = `${parent.name}@example.ch`;

    const errors = await login(page, parent);
    // The parent registers the address they forward from
    await tab(page, 'Settings');
    const me = page.locator('div.p-4', { has: page.getByRole('heading', { name: parent.name }) });
    await me.getByLabel(`New e-mail address for ${parent.name}`).fill(address);
    await me.getByRole('button', { name: 'Add address' }).click();
    await expect(me.getByText(address)).toBeVisible();

    // The Cloudflare Email Worker delivers the forwarded mail
    const delivered = await request.post(`${API}/inbound`, {
        data: mail(address),
        headers: { 'Content-Type': 'message/rfc822', 'X-Inbound-Secret': 'e2e-inbound' },
    });
    expect(delivered.ok(), await delivered.text()).toBeTruthy();

    await tab(page, 'Accounts');
    const inbox = page.locator('.glass-card', { has: page.getByRole('heading', { name: /receipt waiting/ }) });
    await expect(inbox.getByText('WG: Ihre Bestellung')).toBeVisible();
    await inbox.getByLabel('Account for WG: Ihre Bestellung').selectOption({ label: 'Migros' });
    await inbox.getByRole('button', { name: 'Release' }).click();

    await expect(page.getByLabel('Name of item 2')).toHaveValue('Velo-Hose');
    await page.getByRole('button', { name: 'Book', exact: true }).click();
    await expect(page.getByRole('heading', { name: /receipt waiting/ })).toHaveCount(0);

    await expect(page.getByRole('button', { name: /2 items/ }).first()).toContainText('📎 1');
    expect(errors).toEqual([]);
});
