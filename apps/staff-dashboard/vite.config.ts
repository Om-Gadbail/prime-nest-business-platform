import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Staff dashboard dev server. The backend base URL is configured via
// VITE_API_BASE_URL (see .env.example) — never hardcoded here.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: false,
  },
  preview: {
    port: 4174,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Playwright specs run via `npm run e2e`, never under vitest.
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
  },
});
