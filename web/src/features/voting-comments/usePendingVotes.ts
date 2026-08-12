/**
 * "What needs my vote" (V5) — `GET /api/v1/me/pending-votes`, refreshed on the two events
 * `design.md` names: `suggestion.vote.updated` (someone's vote changed, possibly clearing
 * the caller off the list or putting them back on it) and `suggestion.created` (a new
 * suggestion is immediately pending).
 */

import { useCallback, useEffect, useState } from 'react'
import { socket } from '../../app/socket'
import type { PendingVotes } from '../../app/types'
import { votesApi } from './api'

const EMPTY: PendingVotes = { count: 0, suggestion_ids: [] }

export function usePendingVotes(tripId: string | null): PendingVotes & { reload: () => Promise<void> } {
  const [pending, setPending] = useState<PendingVotes>(EMPTY)

  const load = useCallback(async () => {
    if (!tripId) {
      setPending(EMPTY)
      return
    }
    try {
      setPending(await votesApi.pending(tripId))
    } catch {
      // Decoration, not a blocking read — a failure here leaves the last-known count.
    }
  }, [tripId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const unsubscribes = [
      socket.subscribe('suggestion.vote.updated', () => void load()),
      socket.subscribe('suggestion.created', () => void load()),
      socket.subscribe('resync', () => void load()),
    ]
    return () => {
      for (const off of unsubscribes) off()
    }
  }, [load])

  return { ...pending, reload: load }
}
