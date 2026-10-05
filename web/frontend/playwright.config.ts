import { defineConfig } from '@playwright/test';

const frontendHost = process.env.PLAYWRIGHT_FRONTEND_HOST || '127.0.0.1';
const frontendPort = process.env.PLAYWRIGHT_FRONTEND_PORT || '4173';
const defaultFrontendUrl = `http://${frontendHost}:${frontendPort}`;
const baseURL = (process.env.PLAYWRIGHT_BASE_URL || defaultFrontendUrl).replace(/\/$/, '');
const webServerUrl = (process.env.PLAYWRIGHT_WEB_SERVER_URL || baseURL).replace(/\/$/, '');
const webServerCommand =
  process.env.PLAYWRIGHT_WEB_SERVER_COMMAND || `npm run dev -- --host ${frontendHost} --port ${frontendPort}`;
const apiBaseUrl = process.env.VITE_API_BASE_URL || 'http://127.0.0.1:18080/api/v1';

export default defineConfig({
  testDir: './e2e',
  testMatch: ['smoke/**/*.smoke.spec.ts'],
  timeout: 30_000,
  use: {
    baseURL,
    headless: true,
  },
  webServer: {
    command: webServerCommand,
    url: webServerUrl,
    reuseExistingServer: true,
    env: {
      VITE_API_BASE_URL: apiBaseUrl,
      VITE_ENABLE_PROJECT_ROADMAP_SEED: 'false',
    },
  },
});
