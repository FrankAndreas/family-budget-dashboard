import path from 'node:path';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

// The Python with the backend's packages; a path is made absolute (Python warns about relative ones with "..")
const configured = process.env.E2E_PYTHON ?? 'python3';
export const PYTHON = configured.includes('/') ? path.resolve(configured) : configured;

export const API = 'http://localhost:8100/api/v1';
const ADMIN_PIN = '1111';
const PIN = '1234';

export interface Parent { name: string; token: string }

// Every test works as a parent of its own (accounts and wishes are private), so tests don't see each other's data
export async function newParent(request: APIRequestContext): Promise<Parent> {
    const admin = await token(request, 'Admin', ADMIN_PIN);
    const name = `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    const created = await request.post(`${API}/users`, {
        data: { username: name, pin: PIN, role: 'PARENT' },
        headers: { Authorization: `Bearer ${admin}` },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    return { name, token: await token(request, name, PIN) };
}

async function token(request: APIRequestContext, username: string, pin: string): Promise<string> {
    const response = await request.post(`${API}/login`, { data: { username, pin } });
    expect(response.ok(), await response.text()).toBeTruthy();
    return (await response.json()).access_token;
}

export async function call<T = any>(
    request: APIRequestContext, parent: Parent, method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, data?: unknown
): Promise<T> {
    const response = await request.fetch(`${API}${path}`, {
        method, data, headers: { Authorization: `Bearer ${parent.token}` },
    });
    expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
}

// Log in through the login page, and fail the test on any error in the browser console
export async function login(page: Page, parent: Parent): Promise<string[]> {
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('dialog', d => d.accept());
    await page.goto('/login');
    await page.locator('#username').fill(parent.name);
    await page.locator('#pin').fill(PIN);
    await page.locator('button[type=submit]').click();
    await expect(page.getByRole('button', { name: 'Logout' })).toBeVisible();
    return errors;
}

export const tab = (page: Page, name: string) => page.getByRole('button', { name, exact: false }).first().click();
