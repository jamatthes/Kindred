/**
 * Refetches distances for another family's perspective (`design.md` D4 / Phase 10:
 * "Switching perspective refetches via `GET /api/v1/distances?family_id=` rather than
 * re-requesting the whole suggestion list"). `null`/the caller's own family needs no fetch
 * at all — every suggestion already carries its own family's row first in
 * `Suggestion.distances`, which is exactly the data this hook would otherwise re-fetch.
 */

import { useEffect, useState } from 'react'
import { socket } from '../../app/socket'
import type { BulkDistancesOut, DistanceStatus } from '../../app/types'
import { distancesApi } from './api'

/** `design.md`'s `distance.updated` payload — narrower than `DistanceOut`: no
 * `family_name`/`family_color`, since the server has no reason to repeat data every
 * subscriber already has. Merged onto the existing cached row below, never used to
 * construct a fresh one (a row this client has never seen has no name/colour to show). */
type DistanceUpdatedPayload = {
  suggestion_id: string
  family_id: string
  status: DistanceStatus
  duration_s: number | null
  distance_m: number | null
  is_estimate: boolean
  computed_at: string | null
}

export function useBulkDistances(
  tripId: string | null,
  perspectiveFamilyId: string | null,
): { bySuggestion: BulkDistancesOut; loading: boolean } {
  const [bySuggestion, setBySuggestion] = useState<BulkDistancesOut>({})
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!tripId || !perspectiveFamilyId) {
      setBySuggestion({})
      return
    }
    let cancelled = false
    setLoading(true)
    distancesApi
      .bulk({ trip_id: tripId, family_id: perspectiveFamilyId })
      .then((result) => {
        if (!cancelled) setBySuggestion(result)
      })
      .catch(() => {
        if (!cancelled) setBySuggestion({})
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tripId, perspectiveFamilyId])

  useEffect(() => {
    if (!tripId || !perspectiveFamilyId) return
    const onUpdated = (envelope: { payload: unknown }) => {
      const payload = envelope.payload as DistanceUpdatedPayload
      if (payload.family_id !== perspectiveFamilyId) return
      setBySuggestion((current) => {
        const existing = current[payload.suggestion_id] ?? []
        const index = existing.findIndex((d) => d.family_id === payload.family_id)
        if (index === -1) return current // no cached row to patch — nothing to lose a name/colour from
        const patched = {
          ...existing[index],
          status: payload.status,
          duration_s: payload.duration_s,
          distance_m: payload.distance_m,
          is_estimate: payload.is_estimate,
          computed_at: payload.computed_at,
        }
        const nextRows = existing.map((d, i) => (i === index ? patched : d))
        return { ...current, [payload.suggestion_id]: nextRows }
      })
    }
    const off = socket.subscribe('distance.updated', onUpdated)
    return off
  }, [tripId, perspectiveFamilyId])

  return { bySuggestion, loading }
}
