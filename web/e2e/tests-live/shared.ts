/**
 * Constants shared by the live-stack smokes (`playwright.live.config.ts`). Mirrors
 * `web/e2e/docker/env.ts`'s role for the isolated suite — the seeded/demo credentials in
 * one place rather than copy-pasted per spec.
 *
 * The demo users (`kindred-demo` password) come from `server/scripts/seed_demo.py`, run
 * once against the live stack's `api` container before this suite — see
 * `playwright.live.config.ts`'s own docblock for the exact steps.
 */

export const SEED_ADMIN_USERNAME = 'admin'
export const SEED_ADMIN_PASSWORD = 'admin'

/** Set by `00-admin-onboarding.spec.ts`, the first spec to run — every later spec logging
 * in as `admin` uses this, not `SEED_ADMIN_PASSWORD`. */
export const ADMIN_PASSWORD_AFTER_ONBOARDING = 'e2e-live-admin-password-1'

export const DEMO_PASSWORD = 'kindred-demo'

/**
 * Get from "the map screen is open" to "the suggestions list is on screen".
 *
 * Since the map-first redesign (`plan/features/map-suggestions/design.md` > "Layout") the
 * list is a drawer summoned from the map toolbar, not a panel docked beside the map — so
 * every spec that reaches a suggestion through its list row has to open it first. Idempotent:
 * a detail card already over the map is dismissed, and a drawer already open is left alone,
 * because specs arrive here in both states depending on what ran before them.
 */
export async function openSuggestionsList(page: import('@playwright/test').Page) {
  const back = page.getByRole('button', { name: /← Back to (list|the map)/ })
  if (await back.isVisible({ timeout: 1_000 }).catch(() => false)) await back.click()

  const toggle = page.locator('.map-suggestions__toolbar').getByRole('button', { name: /^List \(/ })
  if ((await toggle.getAttribute('aria-pressed')) !== 'true') await toggle.click()
}
