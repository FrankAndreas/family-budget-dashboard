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

// The transactions endpoint is paginated; fetch every page for an account
export async function fetchAllTransactions<T>(accountId: string): Promise<T[]> {
    const all: T[] = [];
    for (let skip = 0; ; skip += PAGE_SIZE) {
        const res = await api.get(`/api/v1/accounts/${accountId}/transactions`, {
            params: { skip, limit: PAGE_SIZE },
        });
        all.push(...res.data);
        if (res.data.length < PAGE_SIZE) return all;
    }
}

export default api;
