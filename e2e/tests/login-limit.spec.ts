import { expect, test } from '@playwright/test';
import { API, newParent } from './helpers';

// After 5 wrong PINs the login page says how long the name is locked, even for the right PIN
test('login page shows the lock after too many wrong PINs', async ({ page, request }) => {
    const parent = await newParent(request);
    for (let i = 0; i < 5; i++) {
        const response = await request.post(`${API}/login`, { data: { username: parent.name, pin: '9999' } });
        expect(response.status()).toBe(401);
    }
    await page.goto('/login');
    await page.locator('#username').fill(parent.name);
    await page.locator('#pin').fill('1234');
    await page.locator('button[type=submit]').click();
    await expect(page.getByText('Too many wrong PINs. Try again in 15 minutes.')).toBeVisible();
});
