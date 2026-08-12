/**
 * AddOptionForm — successful add calls back with the created option (what "appends the
 * option" means from this component's own vantage — `PollsScreen.tsx` is what actually puts
 * it on screen, by reloading from the server), a 403 shows the server's message and does not
 * call back, and the coordinate fields only appear once the poll already has a located
 * option.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../app/apiClient'
import type { Poll, PollOption } from '../../app/types'

const addOption = vi.fn()
vi.mock('./api', () => ({ pollsApi: { addOption: (...args: unknown[]) => addOption(...args) } }))

const { AddOptionForm } = await import('./AddOptionForm')

function option(overrides: Partial<PollOption> = {}): PollOption {
  return {
    id: 'opt-1',
    label: 'York',
    lat: null,
    lng: null,
    place_id: null,
    sort: 0,
    created_by: null,
    suggestion_id: null,
    can_delete: false,
    ...overrides,
  }
}

function poll(overrides: Partial<Poll> = {}): Poll {
  return {
    id: 'p1',
    title: 'Where shall we go?',
    kind: 'score_matrix',
    status: 'open',
    option_count: 1,
    comment_count: 0,
    my_completion: 'none',
    group_completion: { complete: 0, partial: 0, none: 1, total: 1 },
    decision: null,
    created_at: '2027-01-01T00:00:00Z',
    description: null,
    allow_member_options: true,
    options: [option()],
    voting_mode: 'score',
    closed_at: null,
    decided_at: null,
    decided_by: null,
    can_nudge: true,
    next_nudge_at: null,
    can_seed_region: false,
    ...overrides,
  }
}

beforeEach(() => addOption.mockReset())

describe('AddOptionForm', () => {
  it('starts collapsed behind a plain "Add an option" affordance', () => {
    render(<AddOptionForm poll={poll()} onAdded={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Add an option' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Option')).not.toBeInTheDocument()
  })

  it('offers no coordinate fields when the poll has no located option yet', () => {
    render(<AddOptionForm poll={poll({ options: [option({ lat: null, lng: null })] })} onAdded={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add an option' }))
    expect(screen.getByLabelText('Option')).toBeInTheDocument()
    expect(screen.queryByLabelText('Latitude')).not.toBeInTheDocument()
  })

  it('offers coordinate fields once the poll is mappable (has a located option)', () => {
    render(<AddOptionForm poll={poll({ options: [option({ lat: 51.5, lng: -0.1 })] })} onAdded={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add an option' }))
    expect(screen.getByLabelText('Latitude')).toBeInTheDocument()
    expect(screen.getByLabelText('Longitude')).toBeInTheDocument()
  })

  it('requires a label before submitting', () => {
    render(<AddOptionForm poll={poll()} onAdded={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add an option' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add option' }))
    expect(screen.getByText('Give the option a label.')).toBeInTheDocument()
    expect(addOption).not.toHaveBeenCalled()
  })

  it('on success, calls back with the created option, clears, and collapses', async () => {
    const created = option({ id: 'new-1', label: 'Northumberland' })
    addOption.mockResolvedValueOnce(created)
    const onAdded = vi.fn()
    render(<AddOptionForm poll={poll()} onAdded={onAdded} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add an option' }))
    fireEvent.change(screen.getByLabelText('Option'), { target: { value: 'Northumberland' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add option' }))

    await waitFor(() => expect(addOption).toHaveBeenCalledWith('p1', { label: 'Northumberland' }))
    await waitFor(() => expect(onAdded).toHaveBeenCalledWith(created))
    // Collapsed back to the plain affordance — ready for the next add, not left mid-entry.
    expect(screen.getByRole('button', { name: 'Add an option' })).toBeInTheDocument()
  })

  it('sends coordinates only when both are filled in', async () => {
    addOption.mockResolvedValueOnce(option())
    render(<AddOptionForm poll={poll({ options: [option({ lat: 51.5, lng: -0.1 })] })} onAdded={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add an option' }))
    fireEvent.change(screen.getByLabelText('Option'), { target: { value: 'Somerset' } })
    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '51.1' } })
    // Longitude left blank.
    fireEvent.click(screen.getByRole('button', { name: 'Add option' }))
    await waitFor(() => expect(addOption).toHaveBeenCalledWith('p1', { label: 'Somerset' }))
  })

  it('on a 403 (member options disabled), shows the server message and does not call back', async () => {
    addOption.mockRejectedValueOnce(
      new ApiError(403, 'member_options_disabled', 'The organiser has not enabled member options for this poll.'),
    )
    const onAdded = vi.fn()
    render(<AddOptionForm poll={poll()} onAdded={onAdded} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add an option' }))
    fireEvent.change(screen.getByLabelText('Option'), { target: { value: 'Northumberland' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add option' }))

    expect(await screen.findByText('The organiser has not enabled member options for this poll.')).toBeInTheDocument()
    expect(onAdded).not.toHaveBeenCalled()
    // Stays open with what was typed, so the attempt is not lost.
    expect(screen.getByLabelText('Option')).toHaveValue('Northumberland')
  })
})
