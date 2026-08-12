/**
 * The list view: empty states (`design.md`), row click writing the shared selection
 * (`store.ts`), and the tri-state sort `DataTable` provides applied to a real suggestion
 * column (votes).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SuggestionsList } from './SuggestionsList'
import { suggestionStore } from './store'
import type { Suggestion } from '../../app/types'

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
    vote_summary: { mode: 'score', count: 3, average: 7, up: null, down: null, my_vote: null },
    comment_count: 2,
    distances: [],
    children: [],
    created_at: '2027-01-01T00:00:00Z',
    updated_at: '2027-01-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => suggestionStore.reset())

describe('SuggestionsList — empty states', () => {
  it('shows the no-suggestions empty state with an inline create action when there are no filters', () => {
    const onCreate = vi.fn()
    render(<SuggestionsList suggestions={[]} onCreate={onCreate} />)
    expect(screen.getByText('No suggestions yet — drop the first pin.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Suggest a place' }))
    expect(onCreate).toHaveBeenCalled()
  })

  it('shows the filtered-empty state with a clear-filters action when filters are active', () => {
    suggestionStore.toggleType('meal')
    render(<SuggestionsList suggestions={[]} />)
    expect(screen.getByText('No suggestions match these filters.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(suggestionStore.getState().filters.types).toEqual([])
  })
})

describe('SuggestionsList — selection sync', () => {
  it('clicking a row writes the shared selection', () => {
    render(<SuggestionsList suggestions={[suggestion({ id: 'row-1' })]} />)
    fireEvent.click(screen.getByText('Harbour House'))
    expect(suggestionStore.getState().selectedId).toBe('row-1')
  })
})

describe('SuggestionsList — sortable columns', () => {
  it('sorts by votes, tri-state: asc → desc → original', () => {
    render(
      <SuggestionsList
        suggestions={[
          suggestion({ id: 'low', title: 'Low', vote_summary: { mode: 'score', count: 1, average: 2, up: null, down: null, my_vote: null } }),
          suggestion({ id: 'high', title: 'High', vote_summary: { mode: 'score', count: 1, average: 9, up: null, down: null, my_vote: null } }),
        ]}
      />,
    )
    const votesHeader = screen.getByRole('button', { name: /Votes/ })

    fireEvent.click(votesHeader) // asc
    let rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Low')

    fireEvent.click(votesHeader) // desc
    rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('High')

    fireEvent.click(votesHeader) // back to original order
    rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Low')
  })

  it('sorts distance real -> estimate -> failed/no_home -> no_route (distances design.md)', () => {
    const own = (d: Partial<Suggestion['distances'][number]>): Suggestion['distances'] => [
      {
        family_id: 'own',
        family_name: 'Us',
        family_color: 1,
        status: 'ok',
        duration_s: null,
        distance_m: null,
        is_estimate: false,
        computed_at: null,
        ...d,
      },
    ]
    render(
      <SuggestionsList
        ownFamilyId="own"
        suggestions={[
          suggestion({ id: 'route', title: 'NoRoute', distances: own({ status: 'no_route', duration_s: null, distance_m: null }) }),
          suggestion({ id: 'real', title: 'Real', distances: own({ status: 'ok', duration_s: 1800 }) }),
          suggestion({ id: 'est', title: 'Estimate', distances: own({ status: 'pending', duration_s: null, distance_m: 5000, is_estimate: true }) }),
          suggestion({ id: 'fail', title: 'Failed', distances: own({ status: 'failed', duration_s: null, distance_m: null }) }),
        ]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Distance/ })) // asc
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('Real'),
      expect.stringContaining('Estimate'),
      expect.stringContaining('Failed'),
      expect.stringContaining('NoRoute'),
    ])
  })
})
