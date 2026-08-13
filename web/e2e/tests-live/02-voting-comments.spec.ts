/**
 * voting-comments smoke: a member votes and comments on the suggestion `01-map-suggestions`
 * created, the organiser approves it, and the status shows live — plus the two-tab live
 * check the M3 integration pass asks for: the organiser's panel, already open and never
 * reloaded, picks up the member's vote (WS `suggestion.vote.updated`) and the approve (WS
 * `suggestion.status_changed`) from a *second*, independent browser session.
 *
 * Runs after `01-map-suggestions` (`02-` prefix): it acts on that spec's suggestion by
 * title, found via the list rather than a stored id (specs are separate processes/files;
 * nothing survives between them except what is on the server).
 */
import { expect, test, type Page } from '@playwright/test'
import {
  ADMIN_PASSWORD_AFTER_ONBOARDING,
  DEMO_PASSWORD,
  SEED_ADMIN_USERNAME,
  openSuggestionsList,
} from './shared'

const SUGGESTION_TITLE = /E2E dropped pin \d+/

async function login(page: Page, username: string, password: string) {
  await page.goto('/')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('navigation', { name: 'Main' }).first()).toBeVisible()
}

async function openSuggestion(page: Page) {
  await page.locator('.rail').getByRole('button', { name: 'Map', exact: true }).click()
  await openSuggestionsList(page)
  // DataTable's rows are plain <tr onClick> ("full-row click targets", design-system.md),
  // not buttons. `.first()`: the list's default sort is created_desc (newest first — see
  // `_apply_sort` in the server's suggestions service), and repeated live-suite runs leave
  // older `E2E dropped pin *` rows from earlier runs in the table, so the regex can match
  // more than one row. The newest (this run's) is always the first match.
  await page.getByRole('row', { name: SUGGESTION_TITLE }).first().click()
  await expect(page.getByRole('heading', { name: SUGGESTION_TITLE })).toBeVisible()
}

test('a member votes and comments, the organiser approves, both see it live in the other session', async ({
  browser,
}) => {
  const organiserContext = await browser.newContext()
  const memberContext = await browser.newContext()

  try {
    const organiserPage = await organiserContext.newPage()
    const memberPage = await memberContext.newPage()

    await login(organiserPage, SEED_ADMIN_USERNAME, ADMIN_PASSWORD_AFTER_ONBOARDING)
    await openSuggestion(organiserPage)

    await login(memberPage, 'jibby', DEMO_PASSWORD)
    await openSuggestion(memberPage)

    // --- vote, live in the other tab -----------------------------------------------------
    const memberPanel = memberPage.locator('.sugg-detail')
    const scoreControl = memberPanel.getByRole('radiogroup', { name: 'Your score' })
    const thumbsControl = memberPanel.getByRole('group', { name: 'Your vote' })
    const isScoreMode = await scoreControl.isVisible({ timeout: 5_000 }).catch(() => false)
    if (isScoreMode) {
      await scoreControl.getByRole('radio', { name: '8', exact: true }).click()
    } else {
      await thumbsControl.getByRole('button', { name: 'Yes' }).click()
    }

    // The organiser's tab was never reloaded or re-selected — this has to arrive over /ws.
    await expect(organiserPage.locator('.sugg-detail')).toContainText(/8\.0|1 vote/, { timeout: 10_000 })

    // --- comment, live in the other tab --------------------------------------------------
    const commentBody = `Looks good to me — E2E ${Date.now()}`
    // Scoped to the posted thread (`.comments`), not the whole panel: right after the click,
    // the composer's own textarea can still transiently hold the same text it is in the
    // middle of clearing (CommentComposer only calls setBody('') once its post() promise
    // resolves), and Playwright's getByText matches a textarea's value as text content —
    // ambiguous against the real, posted comment for the instant both are present.
    const memberThread = memberPanel.locator('.comments')
    await memberPanel.getByLabel('Add a comment').fill(commentBody)
    await memberPanel.getByRole('button', { name: 'Post' }).click()
    await expect(memberThread.getByText(commentBody)).toBeVisible()
    await expect(organiserPage.locator('.sugg-detail').locator('.comments').getByText(commentBody)).toBeVisible({
      timeout: 10_000,
    })

    // --- organiser approves, live in the member's tab -------------------------------------
    const organiserPanel = organiserPage.locator('.sugg-detail')
    await expect(organiserPanel.getByRole('button', { name: 'Approve' })).toBeVisible()
    await organiserPanel.getByRole('button', { name: 'Approve' }).click()
    await expect(organiserPanel.locator('.sugg-status')).toHaveText('Approved')

    // The member's tab, again never reloaded, sees the status flip live.
    await expect(memberPanel.locator('.sugg-status')).toHaveText('Approved', { timeout: 10_000 })

    // Confirm a plain member never sees the admin block at all (absent, not disabled).
    await expect(memberPanel.getByRole('button', { name: 'Approve' })).not.toBeVisible()
  } finally {
    await organiserContext.close()
    await memberContext.close()
  }
})
