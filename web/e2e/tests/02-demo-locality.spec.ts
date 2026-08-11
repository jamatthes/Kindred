/**
 * Demo login -> families list shows locality-not-address for another family (FM-4 privacy
 * rule: a home address is visible only within its own family; everyone else sees the coarse
 * locality, or "No home set" / "Not placed").
 *
 * Logs in as `jibby` (head of The Jiangs, seeded by server/scripts/seed_demo.py) and checks
 * The Parkers' card — a family jibby does not belong to. The Parkers are seeded with a full
 * `home_address` ("12 Elm Row, Bristol BS1 4AA") but only `home_locality` ("Bristol") may
 * appear on a card that is not the viewer's own (web/src/features/families/FamiliesScreen.tsx).
 */
import { expect, test } from '@playwright/test'
import { DEMO_PASSWORD } from '../docker/env'

test('a demo user sees another family\'s locality but not its street address', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('Username').fill('jibby')
  await page.getByLabel('Password', { exact: true }).fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  // shell.tsx renders both a desktop rail (`.rail`) and a mobile tabbar, each with its own
  // `aria-label="Families"` button; shell.css hides the tabbar above the mobile breakpoint
  // and Desktop Chrome (this project's viewport) is well above it, so scope to `.rail`
  // rather than relying on DOM order to pick the visible one.
  await page.locator('.rail').getByRole('button', { name: 'Families', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Families' })).toBeVisible()

  const parkersCard = page.getByRole('button', { name: 'Open The Parkers' })
  await expect(parkersCard).toBeVisible()

  // The locality, in words.
  await expect(parkersCard).toContainText('Bristol')
  // The privacy caption confirms *why* only the locality is there.
  await expect(parkersCard).toContainText('home address visible to them only')
  // The street address must never leak onto a card that is not the viewer's own family.
  await expect(parkersCard).not.toContainText('Elm Row')

  // jibby's own family card, by contrast, is allowed to say "your family" — it does not need
  // to hide anything from its own head, though the card still only ever shows the locality.
  const jiangsCard = page.getByRole('button', { name: 'Open The Jiangs' })
  await expect(jiangsCard).toContainText('your family')
})
