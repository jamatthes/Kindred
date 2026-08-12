/**
 * RecomputeButton — the force-recompute affordance (D7), shared by the single-suggestion
 * case (side panel) and the whole-trip case (admin console). Organiser-only; the caller
 * decides whether to render it at all (permission is presentation here, enforced for real
 * server-side by `require_main_admin`, same courtesy pattern as every other admin control
 * in this app).
 */

import { Banner, Button } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import { useRecompute } from './useRecompute'

export type RecomputeButtonProps = {
  tripId: string
  suggestionId?: string
  label: string
}

export function RecomputeButton({ tripId, suggestionId, label }: RecomputeButtonProps) {
  const { busy, error, run } = useRecompute()
  const toast = useToast()

  async function handleClick() {
    const result = await run(tripId, suggestionId)
    if (result) {
      toast(
        result.queued_pairs === 0
          ? 'Nothing to recompute — every pair already has a real value.'
          : `Queued ${result.queued_pairs} pair${result.queued_pairs === 1 ? '' : 's'} — about ${result.estimated_api_calls} API call${result.estimated_api_calls === 1 ? '' : 's'}.`,
      )
    }
  }

  return (
    <div className="dist-recompute">
      <Button variant="secondary" busy={busy} onClick={() => void handleClick()}>
        {label}
      </Button>
      {error ? <Banner tone="error">{error}</Banner> : null}
    </div>
  )
}
