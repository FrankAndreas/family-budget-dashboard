import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
    resolve: {
        // The workerd runtime module doesn't exist under Node; the tests use a stand-in
        alias: { 'cloudflare:email': fileURLToPath(new URL('./test/cloudflare-email.ts', import.meta.url)) },
    },
});
