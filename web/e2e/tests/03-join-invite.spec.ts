/**
 * Join-invite registration path (FM-7, FM-8): `/join/demo-join-the-jiangs`, the `join`-mode
 * invite server/scripts/seed_demo.py leaves outstanding for The Jiangs.
 *
 * Runs in a fresh, unauthenticated browser context (a real second identity, not the same
 * session as the other specs) so it exercises the actual "visitor with a link and no
 * account" path rather than something already signed in.
 */
import { expect, test } from '@playwright/test'
import { JOIN_INVITE_TOKEN } from '../docker/env'

test('registering through a join invite lands a new member in the app', async ({ browser, baseURL }) => {
  const context = await browser.newContext()
  const page = await context.newPage()

  try {
    await page.goto(`${baseURL}/join/${JOIN_INVITE_TOKEN}`)

    // The preview loads before anything is asked for (JoinScreen.tsx) and names the family.
    await expect(page.getByText(/You're joining The Jiangs on/)).toBeVisible()

    await page.getByLabel('First name').fill('Robin')
    await page.getByLabel('Username').fill('robin-e2e-join')
    await page.getByLabel('Password', { exact: true }).fill('e2e-join-password-1')
    await page.getByLabel('Confirm password').fill('e2e-join-password-1')
    await page.getByRole('button', { name: 'Join the trip' }).click()

    // The response carries `next_step` directly (JoinScreen adopts it without a round trip);
    // for a `join`-mode invite into an existing family that is "app", not "setup_family".
    await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible()

    // Confirm it actually landed Robin in The Jiangs, not merely "some app screen".
    await page.locator('.rail').getByRole('button', { name: 'Families', exact: true }).click()
    const jiangsCard = page.getByRole('button', { name: 'Open The Jiangs' })
    await expect(jiangsCard).toContainText('your family')
    await expect(jiangsCard).toContainText('Robin')
  } finally {
    await context.close()
  }
})
