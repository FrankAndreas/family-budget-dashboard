import { expect, test } from '@playwright/test';
import { API, login, newParent } from './helpers';

// Wrong PINs entered for a name are shown to that person at their next login (issue #86)
test('the next login shows wrong PINs entered for the name', async ({ page, request }) => {
    const parent = await newParent(request);
    for (let i = 0; i < 2; i++) {
        const response = await request.post(`${API}/login`, { data: { username: parent.name, pin: '0000' } });
        expect(response.status()).toBe(401);
    }
    const errors = await login(page, parent);
    const notice = page.getByRole('alert');
    await expect(notice).toContainText('2 wrong PINs were entered for your name since your last login');
    await page.getByRole('button', { name: 'Got it' }).click();
    await expect(notice).toHaveCount(0);
    expect(errors).toEqual([]);
});
