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
