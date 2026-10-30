import path from 'node:path';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

// The Python with the backend's packages; a path is made absolute (Python warns about relative ones with "..")
const configured = process.env.E2E_PYTHON ?? 'python3';
export const PYTHON = configured.includes('/') ? path.resolve(configured) : configured;

export const API = 'http://localhost:8100/api/v1';
// The family hub the app logs in through (a real one, from a family-hub checkout: playwright.config.ts)
export const HUB = 'http://localhost:8120';
const ADMIN_PIN = '1111';
const PIN = '1234';

export interface Parent { name: string; token: string }

// The hub's login token for a person: the hub only sets it as the cookie, which this API context then drops again
async function hubToken(request: APIRequestContext, name: string, pin: string): Promise<string> {
    const response = await request.post(`${HUB}/api/login`, { data: { name, pin } });
    expect(response.ok(), await response.text()).toBeTruthy();
    const cookie = response.headersArray().find(h => h.name.toLowerCase() === 'set-cookie' && h.value.startsWith('hub_session='));
    expect(cookie, 'the hub sets hub_session').toBeTruthy();
    await request.post(`${HUB}/api/logout`);
    return cookie!.value.split(';')[0].slice('hub_session='.length);
}

async function asHubAdmin<T = any>(request: APIRequestContext, method: string, path: string, data?: unknown): Promise<T> {
    const token = await hubToken(request, 'Admin', ADMIN_PIN);
    const response = await request.fetch(`${HUB}${path}`, { method, data, headers: { Cookie: `hub_session=${token}` } });
    expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
}

// A person in the hub with access to this app (the hub tile with the key "budget", made on first use)
export async function addToHub(request: APIRequestContext, name: string, role: 'PARENT' | 'CHILD', access = true): Promise<number> {
    const person = await asHubAdmin(request, 'POST', '/api/people', { name, pin: PIN, role });
    if (access) await giveAccess(request, person.id, true);
    return person.id;
}

export async function giveAccess(request: APIRequestContext, personId: number, access: boolean): Promise<void> {
    const tiles = await asHubAdmin<{ id: number; app_key: string | null; people: number[] }[]>(request, 'GET', '/api/tiles/manage');
    let tile = tiles.find(t => t.app_key === 'budget');
    if (!tile) {
        tile = await asHubAdmin(request, 'POST', '/api/tiles', { name: 'Budget', local_url: 'http://localhost:3100', app_key: 'budget' });
    }
    const people = access ? [...new Set([...tile!.people, personId])] : tile!.people.filter(id => id !== personId);
    await asHubAdmin(request, 'PATCH', `/api/tiles/${tile!.id}`, { people });
}

// The person picks a language in the hub (where it lives now); the app follows within a minute, at once for a login
// it hasn't seen yet
export async function setHubLanguage(request: APIRequestContext, person: Parent, language: 'de' | 'en'): Promise<void> {
    const response = await request.fetch(`${HUB}/api/me`, {
        method: 'PATCH', data: { language }, headers: { Cookie: `hub_session=${person.token}` },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
}

// A family member logged in at the hub (their token), for people the tests add themselves
export async function hubLogin(request: APIRequestContext, name: string): Promise<Parent> {
    return { name, token: await hubToken(request, name, PIN) };
}

// Every test works as a parent of its own (accounts and wishes are private), so tests don't see each other's data
export async function newParent(request: APIRequestContext): Promise<Parent> {
    const name = `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    await addToHub(request, name, 'PARENT');
    return hubLogin(request, name);
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

// Logged in as at home: the hub's cookie in the browser (the hub's own login page is family-hub's to test). Fails the
// test on any error in the browser console
export async function login(page: Page, parent: Parent): Promise<string[]> {
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('dialog', d => d.accept());
    await page.context().addCookies([{ name: 'hub_session', value: parent.token, url: 'http://localhost:3100' }]);
    await page.goto('/');
    await expect(page.getByRole('button', { name: /^(Logout|Abmelden)$/ })).toBeVisible();
    return errors;
}

export const tab = (page: Page, name: string) => page.getByRole('button', { name, exact: false }).first().click();
