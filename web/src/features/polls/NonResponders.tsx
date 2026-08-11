/**
 * "3 of 9 haven't voted yet" (PL-9), and the nudge that chases them (PL-10).
 *
 * **The names are visible to everyone.** That is deliberate and stated in the requirements:
 * this is a family group deciding together, not an anonymous ballot, and chasing people is
 * the point. Hiding the names would make the count useless.
 *
 * Not-started and partly-done are shown separately, because they are a different
 * conversation — one person has not looked, the other got halfway and stopped.
 */

import { useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Button } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import type { Poll, PollResults } from '../../app/types'
import { pollsApi } from './api'

export function NonResponders({
  results,
  poll,
  canNudge,
}: {
  results: PollResults
  poll: Poll
  canNudge: boolean
}) {
  const toast = useToast()
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nudged, setNudged] = useState<string | null>(null)

  const { count, total, users } = results.non_responders
  const notStarted = users.filter((u) => u.completion === 'none')
  const partly = users.filter((u) => u.completion === 'partial')

  async function nudge() {
    setBusy(true)
    setError(null)
    try {
      const result = await pollsApi.nudge(poll.id)
      setNudged(result.message)
      toast(result.message)
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : 'They could not be nudged just now.',
      )
    } finally {
      setBusy(false)
    }
  }

  if (count === 0) {
    return (
      <p className="nonresponders nonresponders--done">Everyone has voted.</p>
    )
  }

  return (
    <div className="nonresponders">
      <button
        type="button"
        className="nonresponders__summary"
        aria-expanded={expanded}
        onClick={() => setExpanded((open) => !open)}
      >
        <strong className="tabular">
          {count} of {total}
        </strong>{' '}
        {count === 1 ? "hasn't" : "haven't"} voted yet
      </button>

      {canNudge && poll.status === 'open' ? (
        <Button
          variant="secondary"
          busy={busy}
          // Disabled once used, with the reason — the server enforces the four-hour window
          // regardless; this stops the button lying about being available.
          disabled={!poll.can_nudge || Boolean(nudged)}
          onClick={() => void nudge()}
        >
          {nudged ? 'Nudged' : 'Nudge'}
        </Button>
      ) : null}

      {error ? <span className="nonresponders__error">{error}</span> : null}

      {expanded ? (
        <div className="nonresponders__names">
          {notStarted.length > 0 ? (
            <p>
              <span className="muted">Not started:</span>{' '}
              {notStarted.map((u) => u.display_name).join(', ')}
            </p>
          ) : null}
          {partly.length > 0 ? (
            <p>
              <span className="muted">Partly done:</span>{' '}
              {partly.map((u) => u.display_name).join(', ')}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
