import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend for /api (API_PROXY, default the dev backend on :8000): same origin as the page, as nginx does in the
// container, so the family hub's login cookie comes along
const backend = process.env.API_PROXY ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { port: 3000, proxy: { '/api': backend } },
})
