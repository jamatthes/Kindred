/**
 * Playwright config for the e2e harness (test(e2e): scaffold).
 *
 * Chromium only — see README.md for why. `baseURL` points at the isolated stack that
 * global-setup brings up on KINDRED_HTTP_PORT (see docker/env.ts); nothing here talks to the
 * dev stack on :8080.
 *
 * This config is NOT wired into `npm run verify` — verify stays fast and network-free.
 * Run this suite with `npm run e2e` from web/.
 */
import { defineConfig, devices } from '@playwright/test'
import { E2E_HTTP_PORT } from './docker/env'

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // tests share one stack/database; keep them serial and predictable
  workers: 1,
  retries: 0, // a flaky smoke gets fixed or deleted (see README), never quietly retried
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'report' }]],
  // Playwright's default `outputDir` ("test-results") is resolved relative to the process's
  // cwd (web/), not this config file's directory — pin it under e2e/ so traces/screenshots
  // land next to the rest of the harness instead of a stray directory in web/.
  outputDir: './test-results',
  globalSetup: './global-setup.ts',
  globalTeardown: './global-teardown.ts',
  use: {
    baseURL: `http://localhost:${E2E_HTTP_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
