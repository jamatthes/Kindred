/**
 * WS liveness: a `family.created` broadcast reaching a second, already-open browser tab
 * without a reload (web/src/features/families/useFamilies.ts subscribes to it and upserts).
 *
 * Two real browser contexts (two sessions, two sockets) rather than one page opened twice —
 * that is the part worth testing: the server pushing to a socket it did not just handshake.
 *
 * Runs last (`04-` prefix): it depends on 01-fresh-install having changed the admin password,
 * and it adds a family that 02/03's assertions do not expect to see.
 */
import { expect, test } from '@playwright/test'
import { DEMO_PASSWORD } from '../docker/env'

const ADMIN_PASSWORD_AFTER_01 = 'e2e-admin-password-1'
const NEW_FAMILY_NAME = 'The E2E Watchers'

test('a family created by one session appears live in another, no reload', async ({ browser }) => {
  const organiserContext = await browser.newContext()
  const viewerContext = await browser.newContext()

  try {
    const organiserPage = await organiserContext.newPage()
    const viewerPage = await viewerContext.newPage()

    // Viewer: a demo member, already parked on Families before anything happens, so the
    // update has to arrive over the socket rather than from a fetch this page triggers.
    await viewerPage.goto('/')
    await viewerPage.getByLabel('Username').fill('jibby')
    await viewerPage.getByLabel('Password', { exact: true }).fill(DEMO_PASSWORD)
    await viewerPage.getByRole('button', { name: 'Sign in' }).click()
    await viewerPage.locator('.rail').getByRole('button', { name: 'Families', exact: true }).click()
    await expect(viewerPage.getByRole('heading', { name: 'Families' })).toBeVisible()
    await expect(viewerPage.getByRole('button', { name: `Open ${NEW_FAMILY_NAME}` })).not.toBeVisible()

    // Organiser: the seeded admin, whose password 01-fresh-install already changed. Owners
    // are organisers by construction (deps.py: is_organiser), so the create-family control
    // is offered.
    await organiserPage.goto('/')
    await organiserPage.getByLabel('Username').fill('admin')
    await organiserPage.getByLabel('Password', { exact: true }).fill(ADMIN_PASSWORD_AFTER_01)
    await organiserPage.getByRole('button', { name: 'Sign in' }).click()
    await organiserPage.locator('.rail').getByRole('button', { name: 'Families', exact: true }).click()
    await organiserPage.getByRole('button', { name: 'Or add one myself' }).click()
    await organiserPage.getByLabel('Family name').fill(NEW_FAMILY_NAME)
    await organiserPage.getByRole('button', { name: 'Create family' }).click()
    await expect(organiserPage.getByRole('button', { name: `Open ${NEW_FAMILY_NAME}` })).toBeVisible()

    // Viewer's page was never reloaded and never re-navigated; the card has to have been
    // pushed to it over /ws (family.created -> useFamilies' upsert).
    await expect(viewerPage.getByRole('button', { name: `Open ${NEW_FAMILY_NAME}` })).toBeVisible({
      timeout: 10_000,
    })
  } finally {
    await organiserContext.close()
    await viewerContext.close()
  }
})
