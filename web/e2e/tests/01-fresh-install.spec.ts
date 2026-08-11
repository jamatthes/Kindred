/**
 * Fresh-install gate walk (foundation F-5, admin-console AC-0).
 *
 * admin/admin -> forced password change -> trip setup (owner, trip not setup_complete yet
 * because scripts/seed_demo.py never sets that flag) -> app. Runs first (see the `01-`
 * prefix and playwright.config.ts's `workers: 1` / `fullyParallel: false`): it is the only
 * test that changes the admin password and flips `setup_complete`, both permanent for the
 * life of this stack.
 *
 * Deliberately does NOT hardcode "three screens in this order" — it reads whichever screen
 * is in front of it and reacts, the same way the real client does off `next_step`
 * (server/app/core/onboarding.py). That is what "tolerant of the owner-family-gate change
 * that may merge soon" means in practice: if a future merge inserts or removes a step, this
 * test still passes as long as the server is honest about what screen it put up.
 */
import { expect, test } from '@playwright/test'
import { SEED_ADMIN_PASSWORD, SEED_ADMIN_USERNAME } from '../docker/env'

const NEW_PASSWORD = 'e2e-admin-password-1'

test('admin walks the fresh-install gate to the app', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('Username').fill(SEED_ADMIN_USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(SEED_ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  // Gate 1: forced password change. `must_change_password` outranks every other next_step.
  await expect(page.getByRole('heading', { name: 'Choose a new password' })).toBeVisible()
  await page.getByLabel('Current password').fill(SEED_ADMIN_PASSWORD)
  await page.getByLabel('New password', { exact: true }).fill(NEW_PASSWORD)
  await page.getByLabel('Confirm new password').fill(NEW_PASSWORD)
  await page.getByRole('button', { name: 'Save and continue' }).click()

  // Gate 2: the owner's trip setup, because seed_demo.py never sets Trip.setup_complete.
  // Read the screen rather than assume it appears — an organiser-role change upstream could
  // legitimately remove this step for some accounts without breaking the product.
  const tripSetupHeading = page.getByRole('heading', { name: 'Set up your trip' })
  if (await tripSetupHeading.isVisible({ timeout: 5_000 }).catch(() => false)) {
    const nameField = page.getByLabel('Trip name')
    await nameField.fill(`${await nameField.inputValue()} (e2e)`)
    await page.getByRole('button', { name: 'Create trip' }).click()
  }

  // Gate 3: family setup would appear here for an account mid-invite-acceptance. The seeded
  // platform admin is exempt by design (onboarding.py: is_pending_family short-circuits for
  // is_platform_admin), so this is a courtesy check, not an assumption.
  const familySetupHeading = page.getByRole('heading', { name: 'Name your family' })
  if (await familySetupHeading.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await page.getByLabel('Family name').fill('The E2E Family')
    await page.getByRole('button', { name: 'Create family' }).click()
  }

  // Landed: the app shell's nav rail (app/shell.tsx renders `nav[aria-label="Main"]` in both
  // its desktop-rail and mobile-tabbar layouts) plus the home screen's own heading.
  await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible()
  await expect(page.locator('.home__title')).not.toBeEmpty()
})
