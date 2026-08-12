/**
 * The organiser's actions: close, reopen, decide, delete (PL-12, PL-13).
 *
 * The decision dialog **lists the options with their averages**, so the admin sees the
 * numbers while choosing — including when they are deliberately choosing against the leader,
 * which PL-13 explicitly allows and the record must reflect honestly.
 *
 * Close carries a real confirm naming how many people have not voted, because closing a poll
 * out from under people is not recoverable by them. Reopen has none: it restores capability
 * rather than removing it.
 */

import { useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import { useToast } from '../../app/ui/toastContext'
import type { Poll, PollResults } from '../../app/types'
import { pollsApi } from './api'
import { optionsByRank } from './ranking'

export function PollAdminBar({
  poll,
  results,
  onChanged,
  onGone,
}: {
  poll: Poll
  results: PollResults
  onChanged: (poll: Poll) => void
  onGone: () => void
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmClose, setConfirmClose] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deciding, setDeciding] = useState(false)
  const [alsoClose, setAlsoClose] = useState(false)

  const outstanding = results.non_responders.count

  async function run(action: () => Promise<Poll | void>, message: string) {
    setBusy(true)
    setError(null)
    try {
      const next = await action()
      if (next) onChanged(next)
      toast(message)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That could not be done.')
    } finally {
      setBusy(false)
    }
  }

  async function decide(optionId: string) {
    setDeciding(false)
    await run(async () => {
      let next = await pollsApi.setDecision(poll.id, optionId)
      // The two usually happen together but not always, so the dialog offers both and this
      // performs whichever were asked for.
      if (alsoClose && next.status === 'open') next = await pollsApi.close(poll.id)
      return next
    }, 'Decision recorded.')
  }

  return (
    <div className="admin-bar">
      <span className="admin-bar__note">
        Organiser · setting a decision shows the numbers first, including when you choose
        against the leader.
      </span>

      {error ? <Banner tone="error">{error}</Banner> : null}

      {poll.status === 'open' ? (
        <Button variant="secondary" disabled={busy} onClick={() => setConfirmClose(true)}>
          Close poll
        </Button>
      ) : (
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => void run(() => pollsApi.reopen(poll.id), 'Poll reopened.')}
        >
          Reopen
        </Button>
      )}

      {poll.decision ? (
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => void run(() => pollsApi.clearDecision(poll.id), 'Decision cleared.')}
        >
          Clear decision
        </Button>
      ) : null}

      <Button disabled={busy} onClick={() => setDeciding(true)}>
        {poll.decision ? 'Change decision' : 'Mark a decision'}
      </Button>

      <Button variant="ghost" disabled={busy} onClick={() => setConfirmDelete(true)}>
        Delete
      </Button>

      <ConfirmDialog
        open={confirmClose}
        title="Close this poll?"
        body={
          outstanding > 0
            ? `${outstanding} ${outstanding === 1 ? 'person hasn’t' : 'people haven’t'} voted yet. Close anyway?`
            : 'Everyone has voted.'
        }
        consequences={['No more scores or options can be added.', 'The results stay visible.']}
        confirmLabel="Close poll"
        busy={busy}
        onCancel={() => setConfirmClose(false)}
        onConfirm={() => {
          setConfirmClose(false)
          void run(() => pollsApi.close(poll.id), 'Poll closed.')
        }}
      />

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this poll?"
        body={`${poll.title} and everything on it.`}
        consequences={[
          `${results.members.length} people's scores will be deleted.`,
          `${poll.comment_count} comments will be deleted.`,
          'This cannot be undone.',
        ]}
        confirmLabel="Delete poll"
        tone="danger"
        busy={busy}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false)
          void run(async () => {
            await pollsApi.remove(poll.id)
            onGone()
          }, 'Poll deleted.')
        }}
      />

      {deciding ? (
        <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Record the decision">
          <div className="modal-card">
            <h2>Which option won?</h2>
            <p className="muted">
              The winner does not have to be the highest average — record what the group
              actually decided.
            </p>
            <ul className="decide-list">
              {optionsByRank(results).map((option) => (
                <li key={option.option_id}>
                  <button
                    type="button"
                    className="decide-list__option"
                    onClick={() => void decide(option.option_id)}
                  >
                    <span>{option.label}</span>
                    {/* The numbers, while choosing. */}
                    <span className="tabular">
                      {option.average === null ? 'no scores' : option.average}
                      {option.is_split ? ' · split' : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <label className="decide-also">
              <input
                type="checkbox"
                checked={alsoClose}
                onChange={(event) => setAlsoClose(event.target.checked)}
              />
              Close this poll too
            </label>
            <Button variant="ghost" onClick={() => setDeciding(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
