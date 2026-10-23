import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { PYTHON as python } from './tests/helpers';

// The tests start their own backend (fresh SQLite database, admin PIN 1111) and frontend on ports of their own,
// so a dev server on 8000/3000 and its data are never touched. E2E_PYTHON: the Python with the backend's packages.
export const BACKEND = 'http://localhost:8100';
export const FRONTEND = 'http://localhost:3100';
const database = path.resolve(__dirname, '.tmp', 'e2e.db');

export default defineConfig({
    testDir: './tests',
    // One backend and database for all tests; each test works with a parent of its own
    workers: 1,
    retries: process.env.CI ? 1 : 0,
    reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
    use: {
        baseURL: FRONTEND,
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 1000 },
        // The tests find elements by their English texts (one test switches to German itself)
        locale: 'en-US',
        trace: 'retain-on-failure',
        screenshot: 'only-on-failure',
    },
    webServer: [
        {
            command: `mkdir -p "${path.dirname(database)}" && rm -f "${database}" && "${python}" -m uvicorn app.main:app --port 8100`,
            cwd: path.resolve(__dirname, '..', 'backend'),
            url: `${BACKEND}/health`,
            env: {
                DATABASE_URL: `sqlite:///${database}`,
                INITIAL_ADMIN_PIN: '1111',
                SECRET_KEY: 'e2e-only',
                CORS_ORIGINS: FRONTEND,
                DEFAULT_LANGUAGE: 'en',
                // Receipt reading with a fake AI: a fixed Migros receipt, never the real service (issue #56)
                RECEIPT_AI_FAKE: '1',
                INFOMANIAK_AI_TOKEN: 'fake',
                INFOMANIAK_AI_PRODUCT_ID: 'fake',
                // Receipt mails as the Cloudflare Email Worker delivers them (issue #57)
                INBOUND_SECRET: 'e2e-inbound',
            },
            reuseExistingServer: false,
            timeout: 60_000,
        },
        {
            command: 'npx vite --port 3100 --strictPort',
            cwd: path.resolve(__dirname, '..', 'frontend'),
            url: FRONTEND,
            env: { VITE_API_URL: BACKEND },
            reuseExistingServer: false,
            timeout: 60_000,
        },
    ],
});
