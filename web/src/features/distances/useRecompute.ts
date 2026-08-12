/**
 * Force-recompute (D7): the response states the cost *before the background work runs* —
 * `design.md` is explicit that `POST /distances/recompute` answers with `queued_pairs`/
 * `estimated_api_calls` synchronously, ahead of the actual Distance Matrix calls, which
 * happen in the background task this response triggers. There is no separate preview
 * endpoint in the contract, so "states the cost before running" is satisfied by showing the
 * response the moment it arrives — the number is true the instant it's displayed, because
 * the Google calls have not happened yet.
 */

import { useState } from 'react'
import { ApiError } from '../../app/apiClient'
import type { RecomputeResult } from '../../app/types'
import { distancesApi } from './api'

export type RecomputeState = {
  busy: boolean
  error: string | null
  lastResult: RecomputeResult | null
  /** Omit `suggestionId` to recompute the whole trip. */
  run: (tripId: string, suggestionId?: string) => Promise<RecomputeResult | null>
}

export function useRecompute(): RecomputeState {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<RecomputeResult | null>(null)

  async function run(tripId: string, suggestionId?: string): Promise<RecomputeResult | null> {
    setBusy(true)
    setError(null)
    try {
      const result = await distancesApi.recompute({ trip_id: tripId, suggestion_id: suggestionId })
      setLastResult(result)
      return result
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : 'That recompute could not be started.',
      )
      return null
    } finally {
      setBusy(false)
    }
  }

  return { busy, error, lastResult, run }
}
