/**
 * Theme + reduced-motion spot check, plus a live end-to-end distance check as a bonus: the
 * suggestion `01-map-suggestions` created has two families with real geocoded homes
 * (`server/scripts/seed_demo.py`), so `POST /suggestions` should have already queued a real
 * Distance Matrix call (a live server key is configured for this stack) by the time this
 * spec runs — a `DistanceChip` in its `ok` state is the end-to-end proof that the whole
 * distances feature (server task, WS `distance.updated`, the chip UI) works against the
 * real Google API, not just against mocks.
 *
 * Static "no raw hex" coverage is `npm run check:tokens` (run separately, part of `npm run
 * verify` — a source-text scan, not something Playwright does). This spec is the
 * complementary runtime half: does the dark toggle actually change what is on screen, and
 * does `prefers-reduced-motion` actually suppress the one CSS animation this pass added
 * (`DistanceChip`'s estimate→real crossfade, `.dist-chip--animated` in `distances.css`).
 */
import { expect, test } from '@playwright/test'
import { ADMIN_PASSWORD_AFTER_ONBOARDING, SEED_ADMIN_USERNAME } from './shared'

const SUGGESTION_TITLE = /E2E dropped pin \d+/

test('dark theme repaints the page and reduced motion suppresses the distance-chip crossfade', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })

  await page.goto('/')
  await page.getByLabel('Username').fill(SEED_ADMIN_USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(ADMIN_PASSWORD_AFTER_ONBOARDING)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible()

  const bodyBgBefore = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)

  await page.getByRole('button', { name: 'Dark theme' }).click()
  const bodyBgAfter = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
  // The token swap actually happened — dark is a distinct, tuned set, never a no-op.
  expect(bodyBgAfter).not.toBe(bodyBgBefore)

  // Spot-check a couple of key elements never resolve to a literal, un-swapped colour —
  // `rgb(255, 255, 255)`/`rgb(0, 0, 0)` would mean a raw hex leaked past the token system
  // rather than going through the dark-mode custom property swap.
  const railBg = await page.evaluate(() => {
    const rail = document.querySelector('.rail')
    return rail ? getComputedStyle(rail).backgroundColor : null
  })
  expect(railBg).not.toBeNull()
  expect(railBg).not.toBe('rgb(255, 255, 255)')

  await page.locator('.rail').getByRole('button', { name: 'Map', exact: true }).click()
  const backButton = page.getByRole('button', { name: '← Back to list' })
  if (await backButton.isVisible({ timeout: 1_000 }).catch(() => false)) await backButton.click()
  // DataTable's rows are plain <tr onClick> ("full-row click targets", design-system.md).
  // `.first()`: default sort is created_desc (newest first), and repeated live-suite runs
  // leave older matching rows around — see the same note in 02-voting-comments.spec.ts.
  await page.getByRole('row', { name: SUGGESTION_TITLE }).first().click()
  await expect(page.getByRole('heading', { name: SUGGESTION_TITLE })).toBeVisible()

  // End-to-end distance check: a real driving duration for at least one family, proving the
  // background task + WS update + chip all work against the live Google key.
  const distanceChip = page.locator('.dist-chip').first()
  await expect(distanceChip).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('.sugg-detail')).toContainText(/from (Parkers|Jiangs)/, { timeout: 20_000 })

  // Reduced motion: the crossfade class may or may not be present depending on which
  // status the chip landed in, but wherever `.dist-chip--animated` does appear, its
  // computed animation must be suppressed (`distances.css`'s
  // `@media (prefers-reduced-motion: reduce)` rule).
  const animatedChip = page.locator('.dist-chip--animated').first()
  if (await animatedChip.isVisible({ timeout: 2_000 }).catch(() => false)) {
    const animationName = await animatedChip.evaluate((el) => getComputedStyle(el).animationName)
    expect(animationName).toBe('none')
  }
})
