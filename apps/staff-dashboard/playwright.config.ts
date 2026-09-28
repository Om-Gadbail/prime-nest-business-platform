import { defineConfig, devices } from '@playwright/test';

/** Smoke E2E against the production preview server (no backend needed). */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5174',
    trace: 'off',
  },
  projects: [
    { name: 'mobile-360', use: { ...devices['Pixel 5'] } },
    { name: 'tablet-768', use: { viewport: { width: 768, height: 1024 } } },
    { name: 'desktop-1280', use: { viewport: { width: 1280, height: 800 } } },
  ],
  webServer: {
    // Port 5174 is an explicitly allowed CORS origin on the backend
    // (PUBLIC_SITE_ORIGINS) — exact-origin matching, no wildcards.
    command: 'npx vite preview --port 5174 --strictPort --host localhost',
    url: 'http://localhost:5174',
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
