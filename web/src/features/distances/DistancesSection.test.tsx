/**
 * DistancesSection (admin console) — the degraded-mode banner (`design.md`: "the main
 * admin sees a banner explaining that the distance service is unavailable") appears only
 * when the failed ratio crosses this feature's documented heuristic threshold.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { BulkDistancesOut, DistanceOut } from '../../app/types'

const bulk = vi.fn()
vi.mock('./api', () => ({ distancesApi: { bulk: (...args: unknown[]) => bulk(...args), recompute: vi.fn() } }))
vi.mock('../../app/ui/toastContext', () => ({ useToast: () => vi.fn() }))

const { DistancesSection } = await import('./DistancesSection')

function row(overrides: Partial<DistanceOut> = {}): DistanceOut {
  return {
    family_id: 'f1',
    family_name: 'Parkers',
    family_color: 1,
    status: 'ok',
    duration_s: 1800,
    distance_m: 30_000,
    is_estimate: false,
    computed_at: null,
    ...overrides,
  }
}

describe('DistancesSection — degraded mode heuristic', () => {
  it('shows no alarming banner when distances are mostly healthy', async () => {
    const bySuggestion: BulkDistancesOut = { s1: [row()], s2: [row()], s3: [row()] }
    bulk.mockResolvedValueOnce(bySuggestion)
    render(<DistancesSection tripId="t1" ownFamilyId="f1" />)
    await waitFor(() => expect(bulk).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the banner once failures cross the threshold with enough of a sample', async () => {
    const bySuggestion: BulkDistancesOut = {
      s1: [row({ status: 'failed', duration_s: null, distance_m: null })],
      s2: [row({ status: 'failed', duration_s: null, distance_m: null })],
      s3: [row()],
    }
    bulk.mockResolvedValueOnce(bySuggestion)
    render(<DistancesSection tripId="t1" ownFamilyId="f1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/distance service looks unavailable/)
  })

  it('always renders the whole-trip recompute action', () => {
    bulk.mockResolvedValueOnce({})
    render(<DistancesSection tripId="t1" ownFamilyId="f1" />)
    expect(screen.getByRole('button', { name: 'Force recompute — whole trip' })).toBeInTheDocument()
  })
})
