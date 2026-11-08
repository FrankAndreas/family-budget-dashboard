import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { answerConfirmsYourself, appConfirm, call, login, newParent, tab } from './helpers';

// Accessibility review 2026-11-08: axe finds nothing on any tab, on a desktop and a phone, so a change that breaks a
// label, a landmark or a heading fails here. Text on the glass cards axe can't measure (it says "incomplete"): those
// colours were checked by hand (slate-400 for secondary text, red-700 under white)
const TABS = ['Accounts', 'Budgets', 'Common', 'Investments', 'Yearly bills', 'Wishes', 'Analytics', 'Settings'];

async function noViolations(page: Page, state: string) {
    const { violations } = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
        .analyze();
    expect(violations.map(v => `${v.id}: ${v.nodes.map(n => n.target.join(' ')).join(', ')}`), state).toEqual([]);
}

// A parent with a partner (the Common tab), an account with bookings and a budget limit
async function family(request: APIRequestContext) {
    const parent = await newParent(request);
    await newParent(request);
    const account = await call(request, parent, 'POST', '/accounts', { name: 'Haushalt', type: 'BANK' });
    const categories = await call(request, parent, 'GET', '/categories');
    const category = (name: string) => categories.find((c: { name: string }) => c.name === name).id;
    for (const [name, amount] of [['Salary', 5000], ['Groceries', 450], ['Rent', 1800]] as const) {
        await call(request, parent, 'POST', '/transactions', { account_id: account.id, category_id: category(name), amount, description: name });
    }
    await call(request, parent, 'POST', '/budgets', { category_id: category('Groceries'), limit: 500, period: 'MONTHLY' });
    return parent;
}

async function everyTab(page: Page, request: APIRequestContext) {
    test.setTimeout(120_000);
    const errors = await login(page, await family(request));
    for (const name of TABS) {
        await tab(page, name);
        await expect(page).toHaveTitle(`${name} · Family Budget`);
        await noViolations(page, name);
    }
    expect(errors).toEqual([]);
}

test('no accessibility violations on any tab', async ({ page, request }) => {
    await everyTab(page, request);
});

test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
    test('no accessibility violations on any tab', async ({ page, request }) => {
        await everyTab(page, request);
    });
});

// The forms that open, the tab shown, the charts' numbers, the confirm dialog's focus
test('forms, tabs, charts and the confirm dialog', async ({ page, request }) => {
    await login(page, await family(request));
    await page.getByRole('button', { name: '+ Add Transaction' }).click();
    for (const field of ['Amount', 'Description', 'Category']) await expect(page.getByLabel(field, { exact: true }).first()).toBeVisible();
    await page.getByRole('button', { name: /Add Account/i }).click();
    await expect(page.getByLabel('Account name')).toBeVisible();
    await noViolations(page, 'booking and account forms');

    const tabs = page.getByRole('navigation', { name: 'Tabs' }).first();
    await tab(page, 'Budgets');
    await expect(tabs.getByRole('button', { name: /Budgets/ })).toHaveAttribute('aria-current', 'page');
    await expect(tabs.getByRole('button', { name: /Accounts/ })).not.toHaveAttribute('aria-current');
    await page.getByRole('button', { name: '+ Set Budget Limit' }).click();
    for (const field of ['Category', 'Budget limit', 'Budget period']) await expect(page.getByLabel(field, { exact: true }).first()).toBeVisible();
    await noViolations(page, 'budget form');

    // Deleting asks; Tab stays in the question, and the focus comes back to the button that asked
    await answerConfirmsYourself(page);
    const remove = page.getByRole('button', { name: 'Delete', exact: true }).first();
    await remove.click();
    const dialog = appConfirm(page);
    await expect(dialog.getByTestId('confirm-yes')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(dialog.getByTestId('confirm-no')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(dialog.getByTestId('confirm-yes')).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(remove).toBeFocused();

    // The charts' numbers as tables for screen readers
    await tab(page, 'Analytics');
    await expect(page.getByRole('table', { name: '6-Month Comparison' })).toContainText("5'000.00");
    await expect(page.getByRole('table', { name: 'Spending per day (this month)' })).toContainText("2'250.00");
});
