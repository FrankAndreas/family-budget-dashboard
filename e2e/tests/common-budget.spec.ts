import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// More than two parents (#18): one line per parent, and settling up asks who pays whom
test('common budget with more than two parents', async ({ page, request }) => {
    const ann = await newParent(request);
    const bea = await newParent(request);
    const cem = await newParent(request);
    const id = async (who: typeof ann) => (await call(request, who, 'GET', '/me')).id;
    const [annId, beaId, cemId] = [await id(ann), await id(bea), await id(cem)];
    // Every active parent needs a percentage (the shared test database has more parents): Bea and Cem 50/50
    const users = await call(request, ann, 'GET', '/users');
    const shares = Object.fromEntries(users
        .filter((u: { role: string; is_active: boolean }) => u.role === 'PARENT' && u.is_active !== false)
        .map((u: { id: string }) => [u.id, u.id === beaId || u.id === cemId ? 50 : 0]));
    const split = await call(request, ann, 'POST', '/splits', { name: `Bea and Cem ${ann.name}`, shares });
    const annAccount = await call(request, ann, 'POST', '/accounts', { name: 'Ann bank', type: 'BANK' });
    const beaAccount = await call(request, bea, 'POST', '/accounts', { name: 'Bea bank', type: 'BANK' });
    await call(request, bea, 'PUT', `/shares/${annId}`, { level: 'VIEW' });
    const categories = await call(request, ann, 'GET', '/categories');
    const groceries = categories.find((c: { name: string }) => c.name === 'Groceries').id;
    await call(request, ann, 'POST', '/transactions', {
        account_id: annAccount.id, category_id: groceries, amount: 100, split_id: split.id,
    });

    const errors = await login(page, ann);
    await page.getByRole('button', { name: 'Common' }).click();
    const balance = page.locator('.glass-card', { has: page.getByRole('heading', { name: 'Balance' }) });
    await expect(balance).toContainText('You are owed CHF 100.00');
    await expect(balance).toContainText(`${bea.name} owes CHF 50.00`);
    await expect(balance).toContainText(`${cem.name} owes CHF 50.00`);

    await balance.getByRole('button', { name: 'Settle up' }).click();
    await balance.getByLabel('Who pays').selectOption(beaId);
    await balance.getByLabel('Who receives').selectOption(annId);
    await expect(balance.getByLabel('Amount')).toHaveValue('50.00');
    await balance.getByLabel(`From ${bea.name}'s account`).selectOption(beaAccount.id);
    await balance.getByLabel('To your account').selectOption(annAccount.id);
    await balance.getByRole('button', { name: 'Record payment' }).click();
    await expect(balance).toContainText('You are owed CHF 50.00');
    await expect(balance).toContainText(`${bea.name} is settled`);
    const net = Object.fromEntries((await call(request, ann, 'GET', '/common/balance'))
        .map((b: { user_id: string; amount: number }) => [b.user_id, b.amount]));
    expect([net[annId], net[beaId], net[cemId]]).toEqual([50, 0, -50]);
    expect(errors).toEqual([]);
});
