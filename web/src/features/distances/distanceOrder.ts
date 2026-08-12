/**
 * The sort-comparator value for one suggestion's distance, from a given family's
 * perspective — `design.md` > "Sorting": "real values ascending, then estimates (marked),
 * then failed/no_home, then no_route last."
 *
 * Returns a single number so `DataTable`'s generic numeric comparator
 * (`app/ui/DataTable.tsx`) can order rows without knowing anything about distance
 * semantics: each tier occupies its own disjoint numeric band, so within a tier the real
 * duration/distance drives the order and across tiers the band ordering wins outright.
 */

import type { DistanceOut } from '../../app/types'

const TIER_REAL = 0
const TIER_ESTIMATE = 1
const TIER_UNAVAILABLE = 2 // failed / no_home
const TIER_NO_ROUTE = 3

/** A band wide enough that no real duration/distance value could cross into the next tier's
 * band — driving durations don't reach ten million seconds. */
const BAND = 10_000_000

export function distanceSortValue(distance: DistanceOut | null | undefined): number {
  if (!distance) return TIER_UNAVAILABLE * BAND
  switch (distance.status) {
    case 'ok':
      // Real values sort by duration when present (what people plan around); fall back to
      // distance if a real row somehow lacks one.
      return TIER_REAL * BAND + (distance.duration_s ?? distance.distance_m ?? 0)
    case 'pending':
      return TIER_ESTIMATE * BAND + (distance.distance_m ?? 0)
    case 'failed':
    case 'no_home':
      return TIER_UNAVAILABLE * BAND
    case 'no_route':
      return TIER_NO_ROUTE * BAND
  }
}

/** Picks the distance row for a given perspective family from a suggestion's distances
 * array, or `null` when that family has no row at all (should not happen once the server
 * always reports `no_home`, but a defensive fallback keeps sorting from throwing). */
export function distanceForFamily(distances: DistanceOut[], familyId: string | null): DistanceOut | null {
  if (!familyId) return distances[0] ?? null // caller's own family is reported first
  return distances.find((d) => d.family_id === familyId) ?? null
}
