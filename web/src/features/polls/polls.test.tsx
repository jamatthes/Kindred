/**
 * The poll UI, at the points where getting it wrong would misrepresent the group's opinion.
 *
 * The honesty rules are the reason this feature exists rather than a spreadsheet, so they are
 * what is tested: an unscored option must not read as a zero, a closed poll must render no
 * voting control rather than a disabled one, and the number on screen must match the number
 * the server sent.
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Poll, PollResults, PollSummary } from '../../app/types'
import { VotingControl } from './VotingControl'
import { optionsByRank } from './ranking'

vi.mock('./api', () => ({
  pollsApi: { putScores: vi.fn(), listComments: vi.fn(), nudge: vi.fn() },
  categoryApi: { read: vi.fn() },
}))

// The screen-level tests below drive PollsScreen directly; these stand in for the app
// context it reads (session, router, trip stage) and for the two data hooks, so the
// layout assertions are about layout and not about the network.
vi.mock('../../app/session', () => ({
  useSession: () => ({
    user: { id: 'me', display_name: 'Me', is_organiser: true, trip: { stage: 'planning' } },
  }),
}))
vi.mock('../../app/router', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../../app/ui/toastContext', () => ({ useToast: () => vi.fn() }))
vi.mock('./usePolls', () => ({
  usePollList: () => ({ polls: [pollSummary()], loading: false, error: null, reload: vi.fn() }),
  usePollDetail: () => ({
    poll: poll(),
    results: results(),
    loading: false,
    error: null,
    setPoll: vi.fn(),
    setResults: vi.fn(),
  }),
}))
vi.mock('./CommentThread', async () => {
  // The real thread fetches on mount; the layout tests only care that it is the fourth
  // panel and carries its own heading.
  return {
    CommentThread: () => (
      <section className="comments poll-block">
        <h2 className="poll-block__head">
          <span>Comments</span>
          <span className="tabular">0</span>
        </h2>
      </section>
    ),
  }
})

const { pollsApi } = await import('./api')

const OPTIONS = [
  { id: 'york', label: 'York', lat: null, lng: null, place_id: null, sort: 0, created_by: null, suggestion_id: null, can_delete: false },
  { id: 'cornwall', label: 'Cornwall', lat: null, lng: null, place_id: null, sort: 1, created_by: null, suggestion_id: null, can_delete: false },
]

function poll(overrides: Partial<Poll> = {}): Poll {
  return {
    id: 'p1',
    title: 'Where shall we go?',
    kind: 'score_matrix',
    status: 'open',
    option_count: 2,
    comment_count: 0,
    my_completion: 'none',
    group_completion: { complete: 0, partial: 0, none: 3, total: 3 },
    decision: null,
    created_at: '2027-02-12T00:00:00Z',
    description: null,
    allow_member_options: false,
    options: OPTIONS,
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

function results(overrides: Partial<PollResults> = {}): PollResults {
  return {
    poll_id: 'p1',
    voting_mode: 'score',
    status: 'open',
    options: [
      {
        option_id: 'cornwall',
        label: 'Cornwall',
        lat: null,
        lng: null,
        average: 7.4,
        response_count: 5,
        spread: 0.5,
        is_split: false,
        is_close: true,
        rank: 1,
        scores: [{ user_id: 'me', display_name: 'Me', family_id: null, family_color: 1, family_color_custom: null, score: 8, thumb: null }],
        up_count: 0,
        down_count: 0,
        none_count: 0,
      },
      {
        option_id: 'york',
        label: 'York',
        lat: null,
        lng: null,
        average: null,
        response_count: 0,
        spread: null,
        is_split: false,
        is_close: false,
        rank: 2,
        scores: [],
        up_count: 0,
        down_count: 0,
        none_count: 3,
      },
    ],
    members: [],
    non_responders: { count: 3, total: 3, users: [] },
    insight: 'Cornwall leads',
    ...overrides,
  }
}

function pollSummary(): PollSummary {
  const base = poll()
  return {
    id: base.id,
    title: base.title,
    kind: base.kind,
    status: base.status,
    option_count: base.option_count,
    comment_count: base.comment_count,
    my_completion: 'partial',
    group_completion: base.group_completion,
    decision: null,
    created_at: base.created_at,
  } as PollSummary
}

describe('the voting control', () => {
  it('labels both ends of the scale in words', () => {
    // "1" and "10" do not say which direction is good, and a poll where half the family
    // scored it backwards is worse than no poll (PL-3).
    render(<VotingControl poll={poll()} results={results()} userId="me" onResults={vi.fn()} />)
    expect(screen.getByText(/Really rather not/)).toBeInTheDocument()
    expect(screen.getByText(/Yes please/)).toBeInTheDocument()
  })

  it('marks an option the member has not scored as unscored, not as zero', () => {
    render(<VotingControl poll={poll()} results={results()} userId="me" onResults={vi.fn()} />)
    expect(screen.getByText('not scored yet')).toBeInTheDocument()
  })

  it('shows the member their own current score', () => {
    render(<VotingControl poll={poll()} results={results()} userId="me" onResults={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Cornwall: 8/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('saves optimistically and keeps the value when the server agrees', async () => {
    const next = results()
    vi.mocked(pollsApi.putScores).mockResolvedValueOnce(next)
    const onResults = vi.fn()

    render(<VotingControl poll={poll()} results={results()} userId="me" onResults={onResults} />)
    fireEvent.click(screen.getByRole('button', { name: /York: 9/ }))

    await waitFor(() => expect(onResults).toHaveBeenCalledWith(next))
    expect(pollsApi.putScores).toHaveBeenCalledWith('p1', [{ option_id: 'york', score: 9 }])
  })

  it('rolls back and explains when the save fails', async () => {
    const { ApiError } = await import('../../app/apiClient')
    vi.mocked(pollsApi.putScores).mockRejectedValueOnce(
      new ApiError(409, 'poll_closed', 'This poll is closed.'),
    )

    render(<VotingControl poll={poll()} results={results()} userId="me" onResults={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /York: 9/ }))

    await waitFor(() => expect(screen.getByText('This poll is closed.')).toBeInTheDocument())
    // The optimistic 9 is gone: York reads unscored again.
    expect(screen.getByText('not scored yet')).toBeInTheDocument()
  })

  it('renders thumbs with words as well as icons', () => {
    render(
      <VotingControl
        poll={poll({ voting_mode: 'thumbs' })}
        results={results({ voting_mode: 'thumbs' })}
        userId="me"
        onResults={vi.fn()}
      />,
    )
    // Colour and glyph are never the only carrier.
    expect(screen.getAllByText('Yes').length).toBeGreaterThan(0)
    expect(screen.getAllByText('No').length).toBeGreaterThan(0)
  })

  it('offers a single choice for an options poll', () => {
    render(
      <VotingControl
        poll={poll({ kind: 'options' })}
        results={results()}
        userId="me"
        onResults={vi.fn()}
      />,
    )
    expect(screen.getByRole('radiogroup')).toBeInTheDocument()
    expect(screen.getAllByRole('radio')).toHaveLength(2)
    // No 1-10 scale anywhere.
    expect(screen.queryByText(/Really rather not/)).not.toBeInTheDocument()
  })
})

describe('ranking', () => {
  it('uses the server ranks rather than sorting locally', () => {
    // Sorting by average here would be a second ranking implementation that could disagree
    // with the server's, including on tie-breaks.
    const ordered = optionsByRank(results())
    expect(ordered.map((o) => o.option_id)).toEqual(['cornwall', 'york'])
  })

  it('keeps an unscored option in the order the server gave it, at the end', () => {
    const ordered = optionsByRank(results())
    expect(ordered[1].average).toBeNull()
  })

  it('tolerates no results at all', () => {
    expect(optionsByRank(null)).toEqual([])
  })
})

/**
 * The detail column's shape. These are the two things a review caught: the list items
 * announced themselves with a paragraph instead of a name, and the detail column ran the
 * five stages together as one undifferentiated stack.
 */
describe('the polls screen layout', () => {
  it('names each poll list item with the poll title, and keeps the status as description', async () => {
    const { PollsScreen } = await import('./PollsScreen')
    render(<PollsScreen selectedId="p1" />)

    const item = await screen.findByRole('button', { name: 'Where shall we go?' })
    expect(item).toBeInTheDocument()
    // The tags/progress are still in the accessible tree, just not in the name.
    expect(item).toHaveAccessibleDescription(/Open/)
  })

  it('groups the detail column into labelled stages in working order', async () => {
    const { PollsScreen } = await import('./PollsScreen')
    render(<PollsScreen selectedId="p1" />)

    await screen.findByRole('heading', { level: 1, name: 'Where shall we go?' })
    const stages = screen
      .getAllByRole('heading', { level: 2 })
      .map((heading) => (heading.firstElementChild ?? heading).textContent)
    // Answer it, see who is missing, read the result, open the detail, then talk.
    expect(stages).toEqual(['Your answer', 'Results', "Everyone's scores", 'Comments'])

    // The nudge line sits between answering and the result, and stays a bare status strip
    // rather than becoming a fifth panel.
    expect(screen.getByText(/haven't voted|Everyone has voted/)).toBeInTheDocument()
  })

  it('puts every stage in its own panel', async () => {
    const { PollsScreen } = await import('./PollsScreen')
    const { container } = render(<PollsScreen selectedId="p1" />)
    await screen.findByRole('heading', { level: 1, name: 'Where shall we go?' })
    expect(container.querySelectorAll('.poll-block').length).toBe(4)
  })

  it('wires the organiser-visible "Add an option" affordance into the matrix panel', async () => {
    // The fixture above is an organiser viewing an open poll — canAddOption.test.ts covers
    // the full role/flag/stage matrix as a pure predicate; this proves it is actually wired
    // into the rendered screen, not just correct in isolation.
    const { PollsScreen } = await import('./PollsScreen')
    render(<PollsScreen selectedId="p1" />)
    expect(await screen.findByRole('button', { name: 'Add an option' })).toBeInTheDocument()
  })
})
