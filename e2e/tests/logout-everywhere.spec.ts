import { expect, test } from '@playwright/test';
import { API, login, newParent } from './helpers';

const me = (request: import('@playwright/test').APIRequestContext, token: string) =>
    request.get(`${API}/me`, { headers: { Authorization: `Bearer ${token}` } });

// Settings → "Log out everywhere" ends every login of that person; changing your own PIN keeps you logged in here
test('log out everywhere, and own PIN change', async ({ page, request }) => {
    const parent = await newParent(request);
    await login(page, parent);
    await page.getByRole('button', { name: 'Settings' }).click();

    // Own PIN change: this browser stays logged in, the other login (the API token) ends
    await page.getByRole('button', { name: 'Change my PIN' }).click();
    await page.getByLabel(`New PIN for ${parent.name}`).fill('5678');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText(`PIN for ${parent.name} changed.`)).toBeVisible();
    expect((await me(request, parent.token)).status()).toBe(401);
    await page.reload();
    await expect(page.getByRole('button', { name: 'Logout' })).toBeVisible();
    await page.getByRole('button', { name: 'Settings' }).click();

    // Log out everywhere: back to the login page, and this browser's token no longer works
    const token = await page.evaluate(() => localStorage.getItem('token'));
    await page.getByRole('button', { name: 'Log out everywhere' }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect((await me(request, token!)).status()).toBe(401);
});
