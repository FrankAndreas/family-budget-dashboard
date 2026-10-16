import axios from 'axios';

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
});

api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Expired or invalid token: drop it and send the user back to the login page
api.interceptors.response.use(
    (response) => response,
    (error) => {
        const isLoginRequest = error.config?.url?.endsWith('/login');
        if (error.response?.status === 401 && !isLoginRequest && localStorage.getItem('token')) {
            localStorage.removeItem('token');
            window.location.href = '/login';
        }
        return Promise.reject(error);
    }
);

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
