/**
 * The admin console's Distances section: the degraded-mode banner and the whole-trip
 * force-recompute affordance (`design.md` > "Degraded mode" / D7). Members never see this —
 * "estimates without an alarming banner — the trip still works" is achieved simply by this
 * section not existing for them, same as every other admin-only console section.
 */

import { Banner } from '../../app/ui/primitives'
import { RecomputeButton } from './RecomputeButton'
import { useDistanceHealth } from './useDistanceHealth'

export function DistancesSection({ tripId, ownFamilyId }: { tripId: string; ownFamilyId: string | null }) {
  const health = useDistanceHealth(tripId, ownFamilyId)

  return (
    <section className="admin__section" id="section-distances" aria-labelledby="distances-heading">
      <h2 className="admin__section-title" id="distances-heading">
        Distances
      </h2>

      {health.degraded ? (
        <Banner tone="error">
          The distance service looks unavailable — {health.failedCount} of {health.sampleCount} recently
          checked pairs failed. Members are seeing straight-line estimates everywhere until this clears.
          Check the Google API key and quota, then force a recompute below.
        </Banner>
      ) : (
        <p className="admin__hint">
          Distances are computed once per family/suggestion pair and cached permanently. Force a
          recompute only when something has clearly gone wrong — it retries every pair, including
          ones already marked unroutable.
        </p>
      )}

      <RecomputeButton tripId={tripId} label="Force recompute — whole trip" />
    </section>
  )
}
