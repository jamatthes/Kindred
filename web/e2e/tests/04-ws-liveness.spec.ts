/**
 * WS liveness: a `family.created` broadcast reaching a second, already-open browser tab
 * without a reload (web/src/features/families/useFamilies.ts subscribes to it and upserts).
 *
 * Distinct browser contexts (separate sessions, separate sockets) rather than one page opened
 * twice — that is the part worth testing: the server pushing to a socket it did not just
 * handshake.
 *
 * The family is born the only way a family can be born since FM-1's 2026-08-11 revision: an
 * organiser hands out a new-family invite, and whoever opens it registers and founds the
 * family themselves (`POST /families/mine`). The old bare `POST /families` and its
 * "Or add one myself" button are gone, so the invite walk is not a workaround here — it is
 * the product's one path, exercised end to end.
 *
 * Runs last (`04-` prefix): it depends on 01-fresh-install having changed the admin password,
 * and it adds a family that 02/03's assertions do not expect to see.
 */
import { expect, test } from '@playwright/test'
import { DEMO_PASSWORD } from '../docker/env'

const ADMIN_PASSWORD_AFTER_01 = 'e2e-admin-password-1'
const NEW_FAMILY_NAME = 'The E2E Watchers'

test('a family founded through an invite appears live in another session, no reload', async ({
  browser,
  baseURL,
}) => {
  const organiserContext = await browser.newContext()
  const viewerContext = await browser.newContext()
  const founderContext = await browser.newContext()

  try {
    const organiserPage = await organiserContext.newPage()
    const viewerPage = await viewerContext.newPage()
    const founderPage = await founderContext.newPage()

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
    // are organisers by construction (deps.py: is_organiser), so the invite card is offered.
    // The raw link is shown exactly once (only its hash is stored), so it is read from the
    // card the moment it exists.
    await organiserPage.goto('/')
    await organiserPage.getByLabel('Username').fill('admin')
    await organiserPage.getByLabel('Password', { exact: true }).fill(ADMIN_PASSWORD_AFTER_01)
    await organiserPage.getByRole('button', { name: 'Sign in' }).click()
    await organiserPage.locator('.rail').getByRole('button', { name: 'Families', exact: true }).click()
    await organiserPage.getByRole('button', { name: 'Create a link' }).click()
    const inviteUrl = (await organiserPage.locator('.invite-once code').innerText()).trim()
    expect(inviteUrl).toContain('/join/')

    // Founder: a visitor with the link and no account. Registration through a create-family
    // invite gates them to setup_family, and naming the family is the act that creates it.
    const invitePath = new URL(inviteUrl).pathname
    await founderPage.goto(`${baseURL}${invitePath}`)
    await expect(founderPage.getByText(/will create a new family/)).toBeVisible()
    await founderPage.getByLabel('First name').fill('Wren')
    await founderPage.getByLabel('Username').fill('wren-e2e-founder')
    await founderPage.getByLabel('Password', { exact: true }).fill('e2e-founder-password-1')
    await founderPage.getByLabel('Confirm password').fill('e2e-founder-password-1')
    await founderPage.getByRole('button', { name: 'Join the trip' }).click()
    await founderPage.getByLabel('Family name').fill(NEW_FAMILY_NAME)
    await founderPage.getByRole('button', { name: 'Create family' }).click()
    await expect(founderPage.getByRole('navigation', { name: 'Main' }).first()).toBeVisible()

    // Viewer's page was never reloaded and never re-navigated; the card has to have been
    // pushed to it over /ws (family.created -> useFamilies' upsert).
    await expect(viewerPage.getByRole('button', { name: `Open ${NEW_FAMILY_NAME}` })).toBeVisible({
      timeout: 10_000,
    })
  } finally {
    await organiserContext.close()
    await viewerContext.close()
    await founderContext.close()
  }
})
