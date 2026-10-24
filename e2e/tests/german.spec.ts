import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Switching to German (#50): menu, a date, a 🔒 category and a backend error in German, then back to English
test('switch the app to German and back', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Bank', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const unsorted = categories.find((c: { system_key: string }) => c.system_key === 'UNSORTED').id;
    await call(request, parent, 'POST', '/transactions', {
        account_id: account.id, category_id: unsorted, amount: 12.5, description: 'Kiosk', date: '2026-10-16T12:00:00',
    });

    const errors = await login(page, parent);
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByLabel('Language').selectOption('de');
    // The page reloads in the person's new language
    await expect(page.getByRole('button', { name: 'Einstellungen' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
    await expect(page.getByRole('button', { name: 'Abmelden' })).toBeVisible();

    // The booking's date in German
    await page.getByRole('button', { name: 'Konten' }).first().click();
    const booking = page.locator('div', { hasText: 'Kiosk' }).last();
    await expect(booking).toContainText('16.10.2026');

    // The 🔒 category by its German name, and a backend error in German
    await page.getByRole('button', { name: 'Einstellungen' }).click();
    const section = page.locator('details', { has: page.getByRole('heading', { name: 'Kategorien' }) });
    // Exactly "Unsortiert" followed by the lock (not a longer word)
    await expect(section.locator('li', { hasText: /Unsortiert\s*🔒/ })).toHaveCount(1);
    await section.getByLabel('Name der neuen Kategorie').fill('Ausgleich');
    await section.getByRole('button', { name: 'Kategorie hinzufügen' }).click();
    await expect(section).toContainText('Eine Kategorie mit diesem Namen gibt es schon');

    await page.getByLabel('Sprache').selectOption('en');
    await expect(page.getByRole('button', { name: 'Settings' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    // The one error is the refused category name (400), which the browser logs
    expect(errors).toEqual(['Failed to load resource: the server responded with a status of 400 (Bad Request)']);
});
