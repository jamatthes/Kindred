/**
 * Section 2 — the stage.
 *
 * The console renders affordances it is given (`can_advance_to`, `can_revert_to`,
 * `blockers`) and calls the one endpoint that moves a stage. It does not know the machine:
 * if it did, the disabled button and the server's refusal would be two implementations of
 * the same rule, and they would drift on the first change to it.
 */

import { useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import type { StageTransition, TripAdmin, TripStage } from '../../app/types'
import { adminApi } from './api'

const STAGE_LABEL: Record<TripStage, string> = {
  planning: 'Planning',
  holiday: 'Holiday',
  end: 'Trip finished',
}

const STAGE_BLURB: Record<TripStage, string> = {
  planning: 'Everyone suggests, votes and settles the plan.',
  holiday: "You're away — check-ins and the now/next view are live.",
  end: 'The trip is finished and everything is read-only.',
}

/** The exact copy from `design.md`. Concrete consequences, never "are you sure?". */
const FORWARD_CONSEQUENCES: Record<string, string[]> = {
  holiday: [
    'Voting and suggestions stay open.',
    'The app switches to the now/next view on phones.',
    'Check-ins become available.',
  ],
  end: [
    'Everyone loses the ability to change anything.',
    'Polls, suggestions, comments and the itinerary become read-only.',
    'You can undo this from here if it was a mistake.',
  ],
}

const FORWARD_VERB: Record<string, string> = {
  holiday: 'Start the holiday',
  end: 'Freeze the trip',
}

/** Machine-readable blockers, rendered in words next to the disabled control. */
const BLOCKER_TEXT: Record<string, string> = {
  missing_dates: 'Set the start and end dates first.',
}

export type StageSectionProps = {
  trip: TripAdmin
  history: StageTransition[]
  onChanged: () => void
}

export function StageSection({ trip, history, onChanged }: StageSectionProps) {
  const [pending, setPending] = useState<{ stage: TripStage; revert: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm() {
    if (pending === null) return
    setBusy(true)
    setError(null)
    try {
      await adminApi.changeStage(trip.id, pending.stage, pending.revert)
      setPending(null)
      onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The stage did not change.')
    } finally {
      setBusy(false)
    }
  }

  const blocked = trip.blockers.length > 0
  const forward = trip.can_advance_to

  return (
    <section className="admin__section" id="section-stage" aria-labelledby="stage-heading">
      <h2 className="admin__section-title" id="stage-heading">
        Stage
      </h2>

      {error ? <Banner tone="error">{error}</Banner> : null}

      <div className="stage__stepper" role="list">
        {(['planning', 'holiday', 'end'] as TripStage[]).map((stage) => (
          <div
            role="listitem"
            key={stage}
            className={`stage__step${stage === trip.stage ? ' is-current' : ''}`}
            aria-current={stage === trip.stage ? 'step' : undefined}
          >
            <span className="stage__step-name">{STAGE_LABEL[stage]}</span>
            <span className="stage__step-blurb">{STAGE_BLURB[stage]}</span>
          </div>
        ))}
      </div>

      <div className="stage__actions">
        {forward !== null || blocked ? (
          <>
            <Button
              disabled={blocked || forward === null}
              onClick={() =>
                forward && setPending({ stage: forward, revert: false })
              }
            >
              {FORWARD_VERB[forward ?? 'holiday'] ??
                `Move to ${STAGE_LABEL[forward ?? 'holiday']}`}
            </Button>
            {blocked ? (
              <span className="admin__hint" role="status">
                {trip.blockers.map((code) => BLOCKER_TEXT[code] ?? code).join(' ')}{' '}
                <a href="#section-trip">Go to trip settings</a>
              </span>
            ) : null}
          </>
        ) : (
          <span className="admin__hint">This trip is finished. There is nowhere forward.</span>
        )}
      </div>

      {trip.can_revert_to !== null ? (
        <div className="stage__revert">
          {/* Visually separated and quieter: a correction, not part of the lifecycle. */}
          <span className="admin__hint">Moved the trip by mistake?</span>
          <Button
            variant="ghost"
            onClick={() =>
              setPending({ stage: trip.can_revert_to as TripStage, revert: true })
            }
          >
            Go back to {STAGE_LABEL[trip.can_revert_to]}
          </Button>
        </div>
      ) : null}

      <h3 className="admin__subheading">History</h3>
      {history.length === 0 ? (
        <p className="admin__hint">The trip has not changed stage yet.</p>
      ) : (
        <table className="admin__mini-table">
          <thead>
            <tr>
              <th scope="col">From</th>
              <th scope="col">To</th>
              <th scope="col">Who</th>
              <th scope="col">When</th>
            </tr>
          </thead>
          <tbody>
            {history.map((row) => (
              <tr key={`${row.created_at}-${row.to_stage}`}>
                <td>{STAGE_LABEL[row.from_stage as TripStage] ?? row.from_stage}</td>
                <td>
                  {STAGE_LABEL[row.to_stage as TripStage] ?? row.to_stage}
                  {row.direction === 'backward' ? (
                    <span className="admin__chip"> correction</span>
                  ) : null}
                </td>
                <td>{row.changed_by?.display_name ?? 'Someone who has since left'}</td>
                <td className="admin__numeric">
                  {new Date(row.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={
          pending?.revert
            ? `Move the trip back to ${STAGE_LABEL[pending.stage]}?`
            : `${FORWARD_VERB[pending?.stage ?? 'holiday'] ?? 'Change stage'}?`
        }
        body={
          pending?.revert
            ? 'This is a correction. The change is recorded in the history either way.'
            : undefined
        }
        consequences={pending && !pending.revert ? FORWARD_CONSEQUENCES[pending.stage] : []}
        confirmLabel={
          pending?.revert
            ? `Go back to ${STAGE_LABEL[pending.stage]}`
            : (FORWARD_VERB[pending?.stage ?? 'holiday'] ?? 'Change stage')
        }
        tone={pending?.stage === 'end' ? 'danger' : 'primary'}
        busy={busy}
        onConfirm={() => void confirm()}
        onCancel={() => setPending(null)}
      />
    </section>
  )
}
