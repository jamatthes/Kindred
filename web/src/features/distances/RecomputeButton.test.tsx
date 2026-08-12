/**
 * RecomputeButton — states the cost as soon as the response arrives (D7: "before the work
 * runs" — there is no separate preview call in the contract, so the toast on the response
 * *is* stating the cost ahead of the background Google calls).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const recompute = vi.fn()
vi.mock('./api', () => ({ distancesApi: { recompute: (...args: unknown[]) => recompute(...args) } }))

const toast = vi.fn()
vi.mock('../../app/ui/toastContext', () => ({ useToast: () => toast }))

const { RecomputeButton } = await import('./RecomputeButton')

describe('RecomputeButton', () => {
  it('calls the endpoint with the trip (and suggestion, when scoped) and toasts the cost', async () => {
    recompute.mockResolvedValueOnce({ queued_pairs: 6, estimated_api_calls: 1 })
    render(<RecomputeButton tripId="t1" suggestionId="s1" label="Force recompute this suggestion" />)
    fireEvent.click(screen.getByRole('button', { name: 'Force recompute this suggestion' }))
    await waitFor(() => expect(recompute).toHaveBeenCalledWith({ trip_id: 't1', suggestion_id: 's1' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Queued 6 pairs — about 1 API call.'))
  })

  it('omits suggestion_id for a whole-trip recompute', async () => {
    recompute.mockResolvedValueOnce({ queued_pairs: 12, estimated_api_calls: 3 })
    render(<RecomputeButton tripId="t1" label="Force recompute — whole trip" />)
    fireEvent.click(screen.getByRole('button', { name: 'Force recompute — whole trip' }))
    await waitFor(() => expect(recompute).toHaveBeenCalledWith({ trip_id: 't1', suggestion_id: undefined }))
  })

  it('surfaces a banner rather than throwing when the request fails', async () => {
    recompute.mockRejectedValueOnce(new Error('nope'))
    render(<RecomputeButton tripId="t1" label="Force recompute — whole trip" />)
    fireEvent.click(screen.getByRole('button', { name: 'Force recompute — whole trip' }))
    expect(await screen.findByText('That recompute could not be started.')).toBeInTheDocument()
  })
})
