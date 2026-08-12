/**
 * map-suggestions smoke: login → create a suggestion via the drop-pin flow → it appears in
 * both the map (a real Google marker renders) and the list.
 *
 * Runs against the real `GoogleMapProvider` (a live browser key is baked into this stack's
 * bundle — see the M3 integration pass) rather than `FakeMapProvider`, which the isolated
 * suite can never exercise (its stack always sets `GOOGLE_MAPS_BROWSER_KEY` empty). Uses the
 * drop-pin creation route rather than search, deliberately: it needs no Places Autocomplete
 * round-trip, only a map click, so the smoke is not at the mercy of Google's prediction
 * service being reachable/deterministic in a CI-like run — `GoogleMapProvider`'s own click
 * handling is still exercised either way.
 */
import { expect, test } from '@playwright/test'
import { ADMIN_PASSWORD_AFTER_ONBOARDING, SEED_ADMIN_USERNAME } from './shared'

const SUGGESTION_TITLE = `E2E dropped pin ${Date.now()}`

test('creating a suggestion by dropping a pin appears on the map and in the list', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill(SEED_ADMIN_USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(ADMIN_PASSWORD_AFTER_ONBOARDING)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible()

  await page.locator('.rail').getByRole('button', { name: 'Map', exact: true }).click()
  const mapCanvas = page.locator('.k-map-canvas')
  await expect(mapCanvas).toBeVisible()
  // Give the real Google Maps JS SDK a moment to load and render tiles before anything
  // clicks it — GoogleMapProvider.mount() is fire-and-forget (see its own comment), so the
  // canvas element exists in the DOM well before the map inside it is actually interactive.
  await page.waitForTimeout(3_000)

  // The map toolbar's "Suggest a place" (opens in search mode, always present) rather than
  // the empty-state list's drop-pin shortcut — that one only exists when the trip has no
  // suggestions yet, which is true at most once per stack lifetime.
  await page.locator('.map-suggestions__toolbar').getByRole('button', { name: 'Suggest a place' }).click()
  const dialog = page.getByRole('dialog', { name: 'Suggest a place' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('tab', { name: 'Drop a pin' }).click()
  await expect(page.getByText('Click anywhere on the map to drop the pin.')).toBeVisible()

  const box = await mapCanvas.boundingBox()
  if (!box) throw new Error('map canvas has no bounding box')
  // Off-centre, deliberately: the "No suggestions yet" empty-state overlay
  // (`.map-suggestions__empty-overlay`) is `pointer-events: none` on its own container but
  // `auto` on its centred button, so a dead-centre click can land on that button instead of
  // the map underneath. A quarter-offset point is clear of it either way.
  await mapCanvas.click({ position: { x: box.width / 4, y: box.height / 4 } })

  await expect(page.getByText(/Pin placed at/)).toBeVisible()
  await dialog.getByLabel('Title').fill(SUGGESTION_TITLE)
  await dialog.getByRole('button', { name: 'Save suggestion' }).click()
  await expect(dialog).not.toBeVisible()

  // Saved and auto-selected: the side panel shows the new suggestion's own detail view.
  await expect(page.getByRole('heading', { name: SUGGESTION_TITLE })).toBeVisible({ timeout: 10_000 })

  // On the map: GoogleMapProvider renders a suggestion pin as a native google.maps.Marker,
  // which the SDK implements as an <img> whose src is the data-URI icon this codebase
  // builds itself (SuggestionPin's own category/glyph vocabulary, see suggestionIcon() in
  // GoogleMapProvider.ts) -- a real marker exists precisely when one of these appears.
  await expect(mapCanvas.locator('img[src^="data:image/svg+xml"]').first()).toBeVisible({ timeout: 10_000 })

  // In the list: back out of the detail panel to the list view and find the row.
  // DataTable's rows are plain <tr onClick> ("full-row click targets", design-system.md),
  // not buttons — the title lives in a table cell.
  await page.getByRole('button', { name: '← Back to list' }).click()
  await expect(page.getByRole('cell', { name: SUGGESTION_TITLE })).toBeVisible()
})
