/**
 * The stage, as feature UIs need it (`admin-console` Phase 10).
 *
 * `canMutate` is **presentation only**. The enforcement is `require_stage` on the server,
 * which every mutating route carries; this exists so a feature can hide a control that would
 * be refused rather than letting someone press it and read an error. Hiding is a courtesy —
 * a feature that used this *instead* of the server guard would have no guard at all.
 *
 * The value is live: the session updates `user.trip.stage` from `stage.changed`, so a
 * control disappears within a second of another admin freezing the trip, without a reload.
 */

import { useSession } from './session'
import type { TripStage } from './types'

export type StageState = {
  stage: TripStage
  /** False in `end`, where the trip is a frozen archive. */
  canMutate: boolean
  isPlanning: boolean
  isHoliday: boolean
  isEnd: boolean
}

export function useStage(): StageState {
  const { user } = useSession()
  // No trip yet is treated as Planning: the only person who can be looking at the app in
  // that state is the owner mid-setup, and nothing they can reach is stage-guarded.
  const stage: TripStage = user?.trip?.stage ?? 'planning'
  return {
    stage,
    canMutate: stage !== 'end',
    isPlanning: stage === 'planning',
    isHoliday: stage === 'holiday',
    isEnd: stage === 'end',
  }
}
