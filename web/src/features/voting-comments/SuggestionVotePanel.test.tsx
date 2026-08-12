/**
 * SuggestionVotePanel — renders the control that matches the resolved mode (score vs
 * thumbs), never a hardcoded one, and the tally's empty state / numeric-as-text rule holds
 * at every density.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoteTally } from '../../app/types'

const read = vi.fn()
vi.mock('./api', () => ({
  votesApi: { read: (...args: unknown[]) => read(...args), upsert: vi.fn(), clear: vi.fn() },
}))

const categoryRead = vi.fn()
vi.mock('../polls/api', () => ({ categoryApi: { read: (...args: unknown[]) => categoryRead(...args) } }))

vi.mock('../../app/socket', () => ({ socket: { subscribe: () => () => {} } }))
vi.mock('../../app/ui/toastContext', () => ({ useToast: () => vi.fn() }))

const { SuggestionVotePanel } = await import('./SuggestionVotePanel')

function tally(overrides: Partial<VoteTally> = {}): VoteTally {
  return {
    mode: 'score',
    count: 0,
    eligible_count: 5,
    average: null,
    distribution: null,
    up: null,
    down: null,
    none: null,
    my_vote: null,
    voters: [],
    not_voted: [],
    ...overrides,
  }
}

beforeEach(() => {
  read.mockReset()
  categoryRead.mockReset()
})

describe('SuggestionVotePanel — mode resolution', () => {
  it('renders the score control (0-10 radiogroup) when the category mode is score', async () => {
    categoryRead.mockResolvedValueOnce([{ category: 'accommodation', voting_mode: 'score' }])
    read.mockResolvedValueOnce(tally())
    render(
      <SuggestionVotePanel
        suggestionId="s1"
        suggestionType="accommodation"
        title="Harbour House"
        density="full"
        canVote
      />,
    )
    await waitFor(() => expect(screen.getByRole('radiogroup')).toBeInTheDocument())
    expect(screen.getAllByRole('radio')).toHaveLength(11) // 0..10
  })

  it('renders the thumbs control when the category mode is thumbs, never the score control', async () => {
    categoryRead.mockResolvedValueOnce([{ category: 'activity', voting_mode: 'thumbs' }])
    read.mockResolvedValueOnce(tally({ mode: 'thumbs', up: 0, down: 0, none: 5 }))
    render(
      <SuggestionVotePanel
        suggestionId="s1"
        suggestionType="activity"
        title="Coasteering"
        density="full"
        canVote
      />,
    )
    await waitFor(() => expect(screen.getByRole('group', { name: 'Your vote' })).toBeInTheDocument())
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
  })
})

describe('SuggestionVotePanel — honesty at zero votes', () => {
  it('never renders a misleading 0.0 average — shows the empty state instead', async () => {
    categoryRead.mockResolvedValueOnce([{ category: 'accommodation', voting_mode: 'score' }])
    read.mockResolvedValueOnce(tally({ count: 0, average: null }))
    render(
      <SuggestionVotePanel
        suggestionId="s1"
        suggestionType="accommodation"
        title="Harbour House"
        density="medium"
        canVote={false}
      />,
    )
    expect((await screen.findAllByText(/no votes yet/i)).length).toBeGreaterThan(0)
    expect(screen.queryByText('0.0')).not.toBeInTheDocument()
  })
})

describe('SuggestionVotePanel — read-only surfaces', () => {
  it('renders the tally but no input control when canVote is false', async () => {
    categoryRead.mockResolvedValueOnce([{ category: 'accommodation', voting_mode: 'score' }])
    read.mockResolvedValueOnce(tally({ count: 2, average: 7 }))
    render(
      <SuggestionVotePanel
        suggestionId="s1"
        suggestionType="accommodation"
        title="Harbour House"
        density="compact"
        canVote={false}
      />,
    )
    await waitFor(() => expect(screen.getByText('7.0')).toBeInTheDocument())
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Your vote' })).not.toBeInTheDocument()
  })
})
