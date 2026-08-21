import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  forbidOnly: !!process.env.CI,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:8765',
    browserName: 'chromium',
    headless: true,
  },
  webServer: {
    command: 'uv run --extra test python scripts/browser_test_server.py',
    url: 'http://127.0.0.1:8765/healthz',
    reuseExistingServer: !process.env.CI,
  },
});
