import { defineConfig, devices } from '@playwright/test'

/**
 * README screenshots, taken from the running demo app (`python tasks.py demo`), never from a real
 * league. Run with `python tasks.py screenshots`; images go to docs/screenshots/.
 */
export default defineConfig({
  testDir: './screenshots',
  testMatch: '**/*.spec.ts',
  workers: 1,
  timeout: 180_000,
  reporter: 'list',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: 'dark',
  },
})
