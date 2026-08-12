/**
 * PendingVotesChip — the count reads honestly at zero ("You're all caught up", not
 * disappearing), and activating it toggles the shared `needsMyVote` filter.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { suggestionStore } from '../map-suggestions/store'

const pending = vi.fn()
vi.mock('./api', () => ({ votesApi: { pending: (...args: unknown[]) => pending(...args) } }))
vi.mock('../../app/socket', () => ({ socket: { subscribe: () => () => {} } }))

const { PendingVotesChip } = await import('./PendingVotesChip')

beforeEach(() => {
  pending.mockReset()
  suggestionStore.reset()
})

describe('PendingVotesChip', () => {
  it('shows the count and pluralises correctly', async () => {
    pending.mockResolvedValueOnce({ count: 3, suggestion_ids: ['a', 'b', 'c'] })
    render(<PendingVotesChip tripId="t1" />)
    expect(await screen.findByText('need your vote')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('shows the quiet zero state rather than disappearing', async () => {
    pending.mockResolvedValueOnce({ count: 0, suggestion_ids: [] })
    render(<PendingVotesChip tripId="t1" />)
    expect(await screen.findByText("You're all caught up")).toBeInTheDocument()
  })

  it('activating it toggles the shared needsMyVote filter', async () => {
    pending.mockResolvedValueOnce({ count: 1, suggestion_ids: ['a'] })
    render(<PendingVotesChip tripId="t1" />)
    await waitFor(() => expect(screen.getByRole('button')).toBeInTheDocument())
    expect(suggestionStore.getState().filters.needsMyVote).toBe(false)
    fireEvent.click(screen.getByRole('button'))
    expect(suggestionStore.getState().filters.needsMyVote).toBe(true)
  })
})
