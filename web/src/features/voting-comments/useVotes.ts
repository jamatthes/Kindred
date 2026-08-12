/**
 * A suggestion's live vote tally, optimistic voting, and WS merge — `design.md` >
 * "Optimistic UI" and "WebSocket events" implemented exactly as specified:
 *
 * 1. Apply locally, mark pending.
 * 2. Fire the request.
 * 3. On success, reconcile with the authoritative tally the response carries.
 * 4. On failure, roll back visibly and let the caller surface a toast.
 * 5. `suggestion.vote.updated` carries the tally **without** `my_vote` (per-recipient,
 *    deliberately excluded from the broadcast) — merged with whatever this client already
 *    knows its own vote to be, never overwritten by the broadcast's absence of it.
 * 6. On reconnect (`resync`), refetch and reconcile.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { socket } from '../../app/socket'
import type { WsEnvelope } from '../../app/wsClient'
import type { Thumb, VoteTally } from '../../app/types'
import { votesApi } from './api'
import {
  applyOptimisticClearScore,
  applyOptimisticClearThumb,
  applyOptimisticScore,
  applyOptimisticThumb,
} from './voteMath'

export type VoteTallyState = {
  tally: VoteTally | null
  loading: boolean
  /** Set only on a failed vote/clear — the rollback's visible explanation. Cleared on the
   * next successful action. */
  error: string | null
  pending: boolean
  vote: (value: number | Thumb) => Promise<void>
  clearVote: () => Promise<void>
  reload: () => Promise<void>
}

export function useVoteTally(suggestionId: string | null): VoteTallyState {
  const [tally, setTally] = useState<VoteTally | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  // Read inside the WS handler, which must not resubscribe on every selection change.
  const idRef = useRef(suggestionId)
  idRef.current = suggestionId
  const lastGoodRef = useRef<VoteTally | null>(null)

  const load = useCallback(async () => {
    if (!suggestionId) {
      setTally(null)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const next = await votesApi.read(suggestionId)
      setTally(next)
      lastGoodRef.current = next
      setError(null)
    } catch {
      setError('The votes could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [suggestionId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const onVoteUpdated = (envelope: WsEnvelope) => {
      // The broadcast nests the tally under `tally` alongside `suggestion_id`
      // (`server/app/routers/votes.py`'s `_tally_and_broadcast`) — it is not the tally's
      // fields flattened onto the envelope. Found by the M3 integration pass's live
      // Playwright smoke: the old flattened cast produced a `VoteTally` whose `voters`/
      // `not_voted`/`mode`/`count` were all `undefined`, which crashed `VoteTally.tsx`'s
      // `.map()` calls the instant a second, already-open tab received this event.
      const payload = envelope.payload as { suggestion_id: string; tally: Omit<VoteTally, 'my_vote'> }
      if (payload.suggestion_id !== idRef.current) return
      setTally((current) => {
        // `my_vote` is per-recipient and never in the broadcast (design.md) — this client's
        // own knowledge of it survives the merge untouched.
        const next: VoteTally = { ...payload.tally, my_vote: current?.my_vote ?? null }
        lastGoodRef.current = next
        return next
      })
    }
    const unsubscribes = [
      socket.subscribe('suggestion.vote.updated', onVoteUpdated),
      socket.subscribe('resync', () => void load()),
    ]
    return () => {
      for (const off of unsubscribes) off()
    }
  }, [load])

  async function vote(value: number | Thumb) {
    if (!suggestionId || !tally) return
    setError(null)
    setPending(true)
    const previous = tally
    const optimistic =
      typeof value === 'number'
        ? applyOptimisticScore(tally, tally.my_vote?.score ?? null, value)
        : applyOptimisticThumb(tally, tally.my_vote?.thumb ?? null, value)
    setTally(optimistic)
    try {
      const body = typeof value === 'number' ? { score: value } : { thumb: value }
      const confirmed = await votesApi.upsert(suggestionId, body)
      setTally({ ...confirmed, my_vote: confirmed.my_vote ?? { [typeof value === 'number' ? 'score' : 'thumb']: value } })
      lastGoodRef.current = confirmed
    } catch {
      // Visible rollback: the control snaps back to what the server last confirmed.
      setTally(previous)
      setError('That vote could not be saved.')
    } finally {
      setPending(false)
    }
  }

  async function clearVote() {
    if (!suggestionId || !tally) return
    setError(null)
    setPending(true)
    const previous = tally
    const optimistic =
      tally.mode === 'score'
        ? applyOptimisticClearScore(tally, tally.my_vote?.score ?? null)
        : applyOptimisticClearThumb(tally, tally.my_vote?.thumb ?? null)
    setTally(optimistic)
    try {
      const confirmed = await votesApi.clear(suggestionId)
      setTally(confirmed)
      lastGoodRef.current = confirmed
    } catch {
      setTally(previous)
      setError('That could not be cleared.')
    } finally {
      setPending(false)
    }
  }

  return { tally, loading, error, pending, vote, clearVote, reload: load }
}
