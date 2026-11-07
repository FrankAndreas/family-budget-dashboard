import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// Finding a booking (UX review 2026-11-07): the list is grouped by month with what came in and went out, every row
// shows its category, and a search and a category filter narrow it down
test('bookings grouped by month, with category, search and filter', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const category = (name: string) => categories.find((c: { name: string }) => c.name === name).id;
    const book = (name: string, amount: number, description: string, date: string) =>
        call(request, parent, 'POST', '/transactions',
            { account_id: account.id, category_id: category(name), amount, description, date: `${date}T12:00:00Z` });
    await book('Salary', 6200, 'Lohn Muster AG', '2026-10-25');
    await book('Rent', 1850, 'Miete Musterweg', '2026-10-01');
    await book('Groceries', 84.35, 'Coop Pronto', '2026-10-12');
    await book('Groceries', 132.1, 'Wocheneinkauf', '2026-09-20');
    const errors = await login(page, parent);

    // Newest month first, each with its income and expenses
    const october = page.getByRole('region', { name: 'October 2026' });
    const september = page.getByRole('region', { name: 'September 2026' });
    await expect(october.getByTestId('month-totals')).toHaveText("+ CHF 6'200.00 · CHF -1'934.35");
    await expect(september.getByTestId('month-totals')).toHaveText('CHF -132.10');
    const headings = await page.getByRole('region').getByRole('heading', { level: 3 }).allInnerTexts();
    expect(headings.indexOf('October 2026')).toBeLessThan(headings.indexOf('September 2026'));

    // The category is on the row
    await expect(october.getByText('Coop Pronto').locator('xpath=../..')).toContainText('Groceries');

    // Search: words in any order, across text and category; the amount works too
    const search = page.getByRole('searchbox', { name: /Search bookings/ });
    await search.fill('groceries coop');
    await expect(page.getByText('Coop Pronto')).toBeVisible();
    await expect(page.getByText('Wocheneinkauf')).toHaveCount(0);
    await expect(october.getByTestId('month-totals')).toContainText('1 found');
    await search.fill('1850');
    await expect(page.getByText('Miete Musterweg')).toBeVisible();
    await expect(page.getByText('Coop Pronto')).toHaveCount(0);
    await search.fill('nothing like this');
    await expect(page.getByText('No bookings match the search.')).toBeVisible();

    // Category filter, then clearing everything shows all bookings again
    await page.getByRole('button', { name: 'Clear' }).click();
    await page.getByRole('combobox', { name: 'Category' }).selectOption({ label: '🛒 Groceries' });
    await expect(page.getByText('Coop Pronto')).toBeVisible();
    await expect(page.getByText('Wocheneinkauf')).toBeVisible();
    await expect(page.getByText('Miete Musterweg')).toHaveCount(0);
    await page.getByRole('button', { name: 'Clear' }).click();
    await expect(page.getByText('Miete Musterweg')).toBeVisible();
    await expect(search).toHaveValue('');
    expect(errors).toEqual([]);
});
