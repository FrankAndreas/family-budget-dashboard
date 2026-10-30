import { expect, test } from '@playwright/test';
import { HUB, addToHub, call, giveAccess, hubLogin, login, newParent, tab } from './helpers';

// Invented names, unique per run: the hub and the app keep one database for all tests
const unique = (prefix: string) => `${prefix}${Date.now().toString(36).slice(-4)}${Math.random().toString(36).slice(2, 5)}`;

// Without the hub's login the app sends the browser to the hub, which sends it back afterwards
test('not logged in → sent to the hub', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(new RegExp(`^${HUB}/\\?next=`));
});

// Someone a parent adds in the hub (with access to this app) is in the family without anything done here
test('a new person in the hub appears in Settings', async ({ page, request }) => {
    const parent = await newParent(request);
    const kid = unique('Kid');
    await addToHub(request, kid, 'CHILD');
    await login(page, parent);
    await tab(page, 'Settings');
    const family = page.locator('details', { has: page.getByRole('heading', { name: 'Family', exact: true }) });
    await expect(family.getByRole('heading', { name: kid })).toBeVisible();
    await expect(family.getByText('No own money: costs are household expenses').first()).toBeVisible();
});

// Removed in the hub: hidden here with the data, which a parent deletes when sure
test('removed in the hub → data deleted after confirming', async ({ page, request }) => {
    const parent = await newParent(request);
    const kid = unique('Gone');
    const kidHubId = await addToHub(request, kid, 'CHILD');
    await call(request, parent, 'GET', '/users');
    await giveAccess(request, kidHubId, false);
    await login(page, parent);
    await tab(page, 'Settings');
    await expect(page.getByRole('heading', { name: 'Removed in the family hub' })).toBeVisible();
    await page.getByRole('button', { name: `Delete the data of ${kid}` }).click();
    await page.getByRole('button', { name: `Remove ${kid}` }).click();
    await expect(page.getByText(`Removed ${kid}.`)).toBeVisible();
    await expect(page.getByRole('button', { name: `Delete the data of ${kid}` })).toHaveCount(0);
});

// A child without Jugendlohn sees what they cost, and nothing else
test('a dependent child sees only their costs', async ({ page, request }) => {
    const parent = await newParent(request);
    const kid = unique('Mia');
    await addToHub(request, kid, 'CHILD');
    const users = await call<{ id: string; username: string }[]>(request, parent, 'GET', '/users');
    const kidId = users.find(u => u.username === kid)!.id;
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Household', type: 'BANK' });
    const categories = await call<{ id: string; name: string }[]>(request, parent, 'GET', '/categories');
    const clothing = categories.find(c => c.name === 'Clothing')!.id;
    await call(request, parent, 'POST', '/transactions', {
        account_id: account.id, category_id: clothing, amount: 25, description: 'Rain jacket', member_id: kidId,
    });

    await login(page, await hubLogin(request, kid));
    await expect(page.getByRole('heading', { name: 'My costs' })).toBeVisible();
    await expect(page.getByText('Rain jacket')).toBeVisible();
    const byCategory = page.getByRole('region', { name: 'By category' });
    await expect(byCategory).toContainText('Clothing');
    await expect(byCategory).toContainText("CHF 25.00");
    await expect(page.getByRole('button', { name: 'Settings' })).toHaveCount(0);
});

// "Log out" ends the login in the hub, for every app, and the hub's login leads back here afterwards
test('log out goes through the hub', async ({ page, request }) => {
    await login(page, await newParent(request));
    await page.getByRole('button', { name: 'Logout' }).click();
    await expect(page).toHaveURL(new RegExp(`^${HUB}/logout\\?next=${encodeURIComponent('http://localhost:3100')}`));
});
