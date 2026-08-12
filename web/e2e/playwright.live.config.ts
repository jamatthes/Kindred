/**
 * Playwright config for smoking the ALREADY-RUNNING deploy stack (`deploy/docker-compose.yml`,
 * whatever `deploy/.env` points it at — typically `http://localhost:1212` on this machine,
 * see `deploy/README.md`), as opposed to `playwright.config.ts`'s isolated throwaway stack.
 *
 * No `globalSetup`/`globalTeardown` here on purpose: this suite does not own the stack's
 * lifecycle. Bring it up yourself (`docker compose -f deploy/docker-compose.yml up -d
 * --build`) and seed it (`docker cp server/scripts/seed_demo.py` into the `api` container,
 * then run it there — see `web/e2e/README.md`'s "How the stack gets seeded" for the exact
 * steps, just against the live container name instead of the isolated one) before running
 * this config. Set `LIVE_BASE_URL` to override the default if your `KINDRED_HTTP_PORT`
 * differs from 1212.
 *
 * Exists because the isolated suite (`playwright.config.ts`) always runs with
 * `GOOGLE_MAPS_BROWSER_KEY` empty (`global-setup.ts`'s generated `.env.e2e`) — it can never
 * exercise the real `GoogleMapProvider`, only `FakeMapProvider`. This config points at the
 * one stack that has real keys, specifically so the map smokes below exercise the real
 * Google Maps JS integration end to end.
 */
import { defineConfig, devices } from '@playwright/test'

const LIVE_BASE_URL = process.env.LIVE_BASE_URL ?? 'http://localhost:1212'

export default defineConfig({
  testDir: './tests-live',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false, // numbered specs share the one live stack/database, same as tests/
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'report-live' }]],
  outputDir: './test-results-live',
  use: {
    baseURL: LIVE_BASE_URL,
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
