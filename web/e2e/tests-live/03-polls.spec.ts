/**
 * polls smoke: create a poll → score an option → the average updates → add an option via
 * the new `AddOptionForm` (the post-M2 fix, `fix/poll-add-option-ui`) → the new option
 * appears in the matrix live off the same `poll_option.created` reload path a second tab's
 * WS event would trigger.
 */
import { expect, test } from '@playwright/test'
import { ADMIN_PASSWORD_AFTER_ONBOARDING, SEED_ADMIN_USERNAME } from './shared'

const POLL_TITLE = `E2E poll ${Date.now()}`
const OPTION_A = 'E2E Option A'
const OPTION_B = 'E2E Option B'
const NEW_OPTION = `E2E added option ${Date.now()}`

test('create a poll, score it, and add an option live', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill(SEED_ADMIN_USERNAME)
  await page.getByLabel('Password', { exact: true }).fill(ADMIN_PASSWORD_AFTER_ONBOARDING)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible()

  await page.locator('.rail').getByRole('button', { name: 'Polls', exact: true }).click()
  // "Polls" is a plain <span> label inside the list aside, not a heading — the aside's own
  // aria-label is the real accessible landmark (PollsScreen.tsx has no <h1>/<h2> for the
  // list itself, only for a poll once one is selected).
  const pollList = page.getByRole('complementary', { name: 'Polls' })
  await expect(pollList).toBeVisible()
  await pollList.getByRole('button', { name: 'Create a poll' }).click()

  const dialog = page.getByRole('dialog', { name: 'Create a poll' })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Question').fill(POLL_TITLE)
  // Score-every-option is the default kind; two option slots already exist.
  // getByRole('textbox', ...) rather than getByLabel: the "Score every option" kind radio's
  // <label> wraps its hint text too ("Everyone rates each option 1–10."), whose accessible
  // name contains the substring "option 1" — ambiguous against getByLabel's default
  // substring match, but unambiguous once scoped to the textbox role.
  await dialog.getByRole('textbox', { name: 'Option 1' }).fill(OPTION_A)
  await dialog.getByRole('textbox', { name: 'Option 2' }).fill(OPTION_B)
  await dialog.getByRole('button', { name: 'Create poll' }).click()
  await expect(dialog).not.toBeVisible()

  await expect(page.getByRole('heading', { level: 1, name: POLL_TITLE })).toBeVisible({ timeout: 10_000 })

  // --- score it, average updates --------------------------------------------------------
  // Several charts on this page share `.k-chart__insight`/"No scores yet" text (this poll's
  // own AvgBar, plus other per-family or per-option widgets) — rather than disambiguate an
  // ambient "before" state, go straight to the one outcome that actually matters: scoring
  // updates AvgBar's accessible table fallback with the real number, per the chart widgets'
  // honesty rules (never just the SVG bar geometry).
  await page.getByRole('button', { name: new RegExp(`^${OPTION_A}: 8`) }).click()
  await expect(page.getByRole('cell', { name: '8.0' })).toBeVisible({ timeout: 10_000 })

  // --- add an option live, via the post-M2 fix -------------------------------------------
  await page.getByRole('button', { name: 'Add an option' }).click()
  await page.getByLabel('Option', { exact: true }).fill(NEW_OPTION)
  await page.getByRole('button', { name: 'Add option' }).click()

  // The matrix is a real <table> (design-system.md's chart-typography note); a fresh column
  // header appearing is the same "poll_option.created inserts the column live" outcome
  // design.md's edge-case table describes for a WS-driven insert, reached here through
  // AddOptionForm's own reload rather than a second tab's broadcast.
  await expect(page.getByRole('columnheader', { name: NEW_OPTION })).toBeVisible({ timeout: 10_000 })
})
