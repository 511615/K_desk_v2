import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: process.env.KDESK_E2E_BASE_URL || 'http://127.0.0.1:8777',
    trace: 'retain-on-failure',
  },
  reporter: [['list'], ['html', { outputFolder: '../runtime/test/playwright-report', open: 'never' }]],
})
