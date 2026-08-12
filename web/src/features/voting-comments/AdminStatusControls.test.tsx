/**
 * AdminStatusControls — V9: only valid transitions render, Reject opens a real confirm
 * dialog and Approve/Shortlist commit directly, the block is entirely absent for a
 * non-admin, and a 409 (racing admin) surfaces an explanation rather than retrying.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../app/apiClient'
import type { Suggestion } from '../../app/types'

const setStatus = vi.fn()
vi.mock('../map-suggestions/api', () => ({
  suggestionsApi: { setStatus: (...args: unknown[]) => setStatus(...args) },
}))

const { AdminStatusControls } = await import('./AdminStatusControls')

function suggestion(overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 's1',
    type: 'accommodation',
    title: 'Harbour House',
    notes: null,
    status: 'proposed',
    created_by: { user_id: 'u1', display_name: 'Alex', family_id: 'f1', family_color: 3 },
    lat: 50.4,
    lng: -4.7,
    geometry_geojson: null,
    place_id: null,
    place_snapshot: null,
    external_url: null,
    vote_summary: null,
    comment_count: 0,
    distances: [],
    children: [],
    created_at: '2027-01-01T00:00:00Z',
    updated_at: '2027-01-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => setStatus.mockReset())

describe('AdminStatusControls — visibility', () => {
  it('renders nothing at all for a non-admin — absence, not a disabled control', () => {
    const { container } = render(
      <AdminStatusControls suggestion={suggestion()} canAdminister={false} onChanged={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders only the transitions valid from the current status', () => {
    render(<AdminStatusControls suggestion={suggestion({ status: 'approved' })} canAdminister onChanged={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Back to shortlisted' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
    // "approved" cannot go straight to "approved" again, and cannot reach "scheduled" here.
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })
})

describe('AdminStatusControls — reject vs approve', () => {
  it('Reject opens a confirm dialog and fires no request until confirmed', () => {
    render(<AdminStatusControls suggestion={suggestion()} canAdminister onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(setStatus).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Reject suggestion' }))
    expect(setStatus).toHaveBeenCalledWith('s1', 'rejected')
  })

  it('dismissing the confirm dialog fires no request', () => {
    render(<AdminStatusControls suggestion={suggestion()} canAdminister onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    fireEvent.click(screen.getByRole('alertdialog').querySelector('.k-btn--secondary')!)
    expect(setStatus).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('Approve and Shortlist commit directly, no confirm dialog', () => {
    setStatus.mockResolvedValue(suggestion({ status: 'approved' }))
    render(<AdminStatusControls suggestion={suggestion()} canAdminister onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(setStatus).toHaveBeenCalledWith('s1', 'approved')
  })
})

describe('AdminStatusControls — racing admin (409)', () => {
  it('surfaces an explanation rather than retrying against a stale status', async () => {
    setStatus.mockRejectedValueOnce(new ApiError(409, 'status_conflict', 'conflict'))
    render(<AdminStatusControls suggestion={suggestion()} canAdminister onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(await screen.findByText(/already changed this suggestion/)).toBeInTheDocument()
    expect(setStatus).toHaveBeenCalledTimes(1) // no automatic retry
  })
})
