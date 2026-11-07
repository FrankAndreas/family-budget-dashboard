import { expect, test } from '@playwright/test';
import { call, login, newParent } from './helpers';

// The top of the overview (UX review 2026-11-07): this month's spending against the budgets and what is left
// instead of counts; an empty inbox and a month check where everything adds up take one line each
test('overview shows the month, quiet when nothing is open', async ({ page, request }) => {
    const parent = await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    await call(request, parent, 'POST', '/accounts', { name: 'Migros', type: 'CLEARING' });
    const categories = await call(request, parent, 'GET', '/categories');
    const category = (name: string) => categories.find((c: { name: string }) => c.name === name).id;
    for (const [name, amount] of [['Salary', 5000], ['Groceries', 450], ['Rent', 1800]] as const) {
        await call(request, parent, 'POST', '/transactions', { account_id: account.id, category_id: category(name), amount });
    }
    await call(request, parent, 'POST', '/budgets', { category_id: category('Groceries'), limit: 500, period: 'MONTHLY' });
    await call(request, parent, 'POST', '/budgets', { category_id: category('Rent'), limit: 1500, period: 'MONTHLY' });
    const errors = await login(page, parent);

    const spent = page.getByTestId('spent-this-month');
    await expect(spent.getByRole('heading', { name: /^Spent in [A-Z][a-z]+$/ })).toBeVisible();
    await expect(spent).toContainText("CHF 2'250.00");
    await expect(spent).toContainText("CHF 2'250.00 of CHF 2'000.00 budgeted");
    await expect(spent).toContainText('1 budget over its limit');
    const left = page.getByTestId('left-this-month');
    await expect(left.getByRole('heading', { name: /^Left in [A-Z][a-z]+$/ })).toBeVisible();
    await expect(left).toContainText("CHF 2'750.00");
    await expect(left).toContainText("Income CHF 5'000.00");
    // The old counts are gone
    await expect(page.getByText('Transactions in Selected Account')).toHaveCount(0);

    // Nothing in the inbox, nothing open in the month check: one line each, no explanation
    await expect(page.getByText('nothing waiting')).toBeVisible();
    const monthCheck = page.getByTestId('month-check');
    await expect(monthCheck).toContainText('Migros: All months add up.');
    await expect(monthCheck).not.toContainText('Clearing accounts should end every month at 0');
    expect((await monthCheck.boundingBox())!.height).toBeLessThan(80);
    expect(errors).toEqual([]);
});
