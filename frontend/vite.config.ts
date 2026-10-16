import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The backend allows this origin (CORS_ORIGINS default in backend/app/main.py)
  server: { port: 3000 },
})
