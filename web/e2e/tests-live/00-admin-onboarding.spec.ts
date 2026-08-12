/**
 * Same gate walk as the isolated suite's `01-fresh-install.spec.ts`, against the live
 * stack. Runs first (`00-` prefix, `playwright.live.config.ts`'s `workers: 1`): it is the
 * one spec that changes the seeded admin's password, which every later spec in this suite
 * depends on. Reads whichever screen is actually in front of it rather than assuming a
 * fixed step count, for the same reason the isolated spec does.
 */
import { expect, test } from '@playwright/test'
import { ADMIN_PASSWORD_AFTER_ONBOARDING, SEED_ADMIN_PASSWORD, SEED_ADMIN_USERNAME } from './shared'

test('admin walks the fresh-install gate to the app', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('Username').fill(SEED_ADMIN_USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(SEED_ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.getByRole('heading', { name: 'Choose a new password' })).toBeVisible()
  await page.getByLabel('Current password').fill(SEED_ADMIN_PASSWORD)
  await page.getByLabel('New password', { exact: true }).fill(ADMIN_PASSWORD_AFTER_ONBOARDING)
  await page.getByLabel('Confirm new password').fill(ADMIN_PASSWORD_AFTER_ONBOARDING)
  await page.getByRole('button', { name: 'Save and continue' }).click()

  const tripSetupHeading = page.getByRole('heading', { name: 'Set up your trip' })
  if (await tripSetupHeading.isVisible({ timeout: 5_000 }).catch(() => false)) {
    const nameField = page.getByLabel('Trip name')
    // seed_demo.py already named the trip "Cornwall · July 2027"; keep it as-is rather than
    // appending a marker, so later specs' assumptions about the trip name still hold.
    if (!(await nameField.inputValue())) await nameField.fill('Cornwall · July 2027')
    await page.getByRole('button', { name: 'Create trip' }).click()
  }

  const familySetupHeading = page.getByRole('heading', { name: 'Name your family' })
  if (await familySetupHeading.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await page.getByLabel('Family name').fill('The Parkers')
    await page.getByRole('button', { name: 'Create family' }).click()
  }

  await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible()
})
