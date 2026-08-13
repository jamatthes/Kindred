/**
 * Section 3 — how each category is voted on.
 *
 * Changes are staged locally and committed with `Save`, and a category that already has
 * votes gets a confirm naming the count. Nothing is deleted either way: the votes stay in
 * the database and stop being *shown* while the other mode is on, which is what the confirm
 * says, because a warning that overstated the damage would train people to ignore it.
 */

import { useEffect, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import type { CategorySetting, VotingCategory, VotingMode } from '../../app/types'
import { adminApi } from './api'

const CATEGORY_LABEL: Record<VotingCategory, string> = {
  poll: 'Polls',
  region: 'Regions',
  accommodation: 'Accommodation',
  activity: 'Activities',
  meal: 'Meals',
  other: 'Other',
}

const CATEGORY_BLURB: Record<VotingCategory, string> = {
  poll: 'Where should we go, how long — the questions with fixed options.',
  region: 'Areas drawn on the map.',
  accommodation: 'Cottages, hotels and campsites.',
  activity: 'Days out, walks and things to book.',
  meal: 'Pubs, cafés and restaurants.',
  other: 'Anything that is none of the above.',
}

const MODE_BLURB: Record<VotingMode, string> = {
  score: 'Members give each option a score from 1 to 10.',
  thumbs: 'Members give a thumbs up or thumbs down.',
}

export type VotingModesSectionProps = {
  settings: CategorySetting[]
  onSaved: (next: CategorySetting[]) => void
  /** End stage: the modes are still worth reading, and can no longer be changed. */
  readOnly?: boolean
}

export function VotingModesSection({
  settings,
  onSaved,
  readOnly = false,
}: VotingModesSectionProps) {
  const [draft, setDraft] = useState<Record<string, VotingMode>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => setDraft({}), [settings])

  const modeOf = (row: CategorySetting): VotingMode => draft[row.category] ?? row.voting_mode
  const changed = settings.filter((row) => modeOf(row) !== row.voting_mode)
  const withVotes = changed.filter((row) => row.existing_vote_count > 0)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      onSaved(
        await adminApi.putCategorySettings(
          changed.map((row) => ({ category: row.category, voting_mode: modeOf(row) })),
        ),
      )
      setDraft({})
      setConfirming(false)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The modes did not save.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="admin__section" id="section-voting" aria-labelledby="voting-heading">
      <h2 className="admin__section-title" id="voting-heading">
        Voting modes
      </h2>
      <p className="admin__hint">
        Switching a mode keeps the votes already cast — they are hidden, not deleted.
      </p>

      {error ? <Banner tone="error">{error}</Banner> : null}

      <table className="admin__mini-table admin__mini-table--roomy">
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">What it covers</th>
            <th scope="col">Mode</th>
          </tr>
        </thead>
        <tbody>
          {settings.map((row) => (
            <tr key={row.category}>
              <td>
                <strong>{CATEGORY_LABEL[row.category]}</strong>
                {row.existing_vote_count > 0 ? (
                  <span className="admin__chip">{row.existing_vote_count} votes</span>
                ) : null}
              </td>
              <td className="admin__muted">{CATEGORY_BLURB[row.category]}</td>
              <td>
                <div
                  className="segmented"
                  role="group"
                  aria-label={`${CATEGORY_LABEL[row.category]} voting mode`}
                >
                  {(['score', 'thumbs'] as VotingMode[]).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      className={modeOf(row) === mode ? 'is-on' : undefined}
                      aria-pressed={modeOf(row) === mode}
                      title={MODE_BLURB[mode]}
                      disabled={readOnly}
                      onClick={() =>
                        setDraft((current) => ({ ...current, [row.category]: mode }))
                      }
                    >
                      {mode === 'score' ? 'Score 1–10' : 'Thumbs'}
                    </button>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="admin__actions">
        {readOnly ? (
          <span className="admin__hint">
            The trip has finished, so the voting modes are fixed.
          </span>
        ) : null}
        <Button
          disabled={readOnly || changed.length === 0}
          busy={busy && !confirming}
          onClick={() => (withVotes.length > 0 ? setConfirming(true) : void save())}
        >
          Save modes
        </Button>
        {changed.length > 0 ? (
          <span className="admin__hint">
            {changed.length} change{changed.length === 1 ? '' : 's'} not saved
          </span>
        ) : null}
      </div>

      <ConfirmDialog
        open={confirming}
        title="Change how this is voted on?"
        body={withVotes
          .map(
            (row) =>
              `${row.existing_vote_count} votes have already been cast on ${CATEGORY_LABEL[
                row.category
              ].toLowerCase()}.`,
          )
          .join(' ')}
        consequences={['They will be kept, but not shown while the new mode is on.']}
        confirmLabel="Change the mode"
        busy={busy}
        onConfirm={() => void save()}
        onCancel={() => setConfirming(false)}
      />
    </section>
  )
}
