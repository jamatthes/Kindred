/**
 * A heuristic read on whether the distance service looks degraded (`design.md` > "Degraded
 * mode": "When rows are broadly `failed` ... show the main admin a banner").
 *
 * **Implementation note — no dedicated health endpoint exists in this feature's contract.**
 * `design.md`'s REST section has no "distance service status" route, so this is assembled
 * from the same bulk read every other consumer uses (`GET /distances`, the caller's own
 * family's perspective across the whole trip) rather than inventing a new endpoint for one
 * banner. A trip is treated as degraded when at least `MIN_SAMPLE` pairs have been attempted
 * and more than `FAILED_RATIO_THRESHOLD` of them settled at `failed` — one bad pair should
 * not alarm the admin, but a quota outage affecting most of the trip should. Both constants
 * are conservative and named here so they are easy to retune once real usage data exists.
 */

import { useEffect, useState } from 'react'
import { distancesApi } from './api'

const MIN_SAMPLE = 3
const FAILED_RATIO_THRESHOLD = 0.3

export type DistanceHealth = { degraded: boolean; failedCount: number; sampleCount: number }

export function useDistanceHealth(tripId: string | null, ownFamilyId: string | null): DistanceHealth {
  const [health, setHealth] = useState<DistanceHealth>({ degraded: false, failedCount: 0, sampleCount: 0 })

  useEffect(() => {
    if (!tripId || !ownFamilyId) return
    let cancelled = false
    distancesApi
      .bulk({ trip_id: tripId, family_id: ownFamilyId })
      .then((bySuggestion) => {
        if (cancelled) return
        const rows = Object.values(bySuggestion).flat()
        const failedCount = rows.filter((r) => r.status === 'failed').length
        const degraded = rows.length >= MIN_SAMPLE && failedCount / rows.length > FAILED_RATIO_THRESHOLD
        setHealth({ degraded, failedCount, sampleCount: rows.length })
      })
      .catch(() => {
        // Decoration, not a blocking read.
      })
    return () => {
      cancelled = true
    }
  }, [tripId, ownFamilyId])

  return health
}
