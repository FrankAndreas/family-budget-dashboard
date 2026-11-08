import axios from 'axios';
import i18n from './i18n';

// Same origin: the family hub's login cookie comes along (nginx, or Vite in development, forwards /api)
const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || '',
});

api.interceptors.request.use((config) => {
    // The backend refuses changes without it: another site can make the browser send the cookie, not this header
    config.headers['X-Requested-With'] = 'budget';
    // Error messages from the backend come in the language on screen (before login too)
    config.headers['Accept-Language'] = i18n.language;
    return config;
});

// The login ended (logged out in the hub, a new PIN): log in at the hub, which sends the browser back here
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (axios.isAxiosError(error) && error.response?.status === 401 && !error.config?.url?.endsWith('/hub')) {
            void goToHub();
        }
        return Promise.reject(error);
    }
);

// Where the family hub's login is, from the backend (HUB_PUBLIC_URL); with next=, the hub sends the browser back
export async function goToHub(next: string | null = window.location.href): Promise<void> {
    const { data } = await api.get<{ login_url: string }>('/api/v1/hub');
    window.location.href = next ? `${data.login_url}/?next=${encodeURIComponent(next)}` : data.login_url;
}

// The hub login is in its last week (the backend's X-Hub-Renew, on loading the page): once through the hub, which
// renews it and sends the browser straight back. At most once a day, in case the renewal doesn't take; without storage
// not at all, so it can never loop (app integration review 2026-11-07)
export const RENEWED_AT = 'hubRenewedAt';
const DAY_MS = 24 * 60 * 60 * 1000;

export function renewNow(
    headers: Record<string, unknown>,
    storage: Pick<Storage, 'getItem' | 'setItem'> | null,
    now: number = Date.now(),
): boolean {
    if (headers['x-hub-renew'] !== '1' || !storage) return false;
    try {
        const last = Number(storage.getItem(RENEWED_AT));
        if (last && now - last < DAY_MS) return false;
        storage.setItem(RENEWED_AT, String(now));
        return true;
    } catch {
        return false;
    }
}

// The browser's storage, if it may be used (blocked site data, private windows: null)
function storage(): Storage | null {
    try {
        return window.localStorage;
    } catch {
        return null;
    }
}

// The hub login is in its last week: through the hub once (renewNow above), which sends the browser back here
export function renewsAtHub(headers: Record<string, unknown>): boolean {
    if (!renewNow(headers, storage())) return false;
    void goToHub();
    return true;
}

// "Log out": the hub ends the login, for this app and every other, then shows its login, which leads back here
export async function goToHubLogout(): Promise<void> {
    const { data } = await api.get<{ login_url: string }>('/api/v1/hub');
    window.location.href = `${data.login_url}/logout?next=${encodeURIComponent(window.location.origin)}`;
}

// The `code` of an error the app acts on (no_access, hub_unavailable, not_logged_in, read_only_child)
export function errorCode(error: unknown): string | undefined {
    return axios.isAxiosError(error) ? error.response?.data?.code : undefined;
}

// Turn an API error into a message for the user (FastAPI sends `detail` as text or a list of validation errors)
export function errorMessage(error: unknown, fallback: string): string {
    if (!axios.isAxiosError(error)) return fallback;
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0) return detail.map((d: { msg: string }) => d.msg).join('; ');
    return fallback;
}

// HTTP status of a failed API call, if there was a response
export function errorStatus(error: unknown): number | undefined {
    return axios.isAxiosError(error) ? error.response?.status : undefined;
}

const PAGE_SIZE = 500;

// The transactions endpoint is paginated; fetch every page for an account. onFirstPage gets the newest bookings as
// soon as they are there, so a list can show them while the older ones are still on their way
export async function fetchAllTransactions<T>(accountId: string, onFirstPage?: (newest: T[]) => void): Promise<T[]> {
    const all: T[] = [];
    for (let skip = 0; ; skip += PAGE_SIZE) {
        const res = await api.get(`/api/v1/accounts/${accountId}/transactions`, {
            params: { skip, limit: PAGE_SIZE },
        });
        all.push(...res.data);
        if (res.data.length < PAGE_SIZE) return all;
        if (skip === 0) onFirstPage?.([...all]);
    }
}

export default api;
