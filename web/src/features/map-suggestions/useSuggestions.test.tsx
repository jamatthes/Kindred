/**
 * `useSuggestionList`'s WS reconciliation — the behaviour `design.md`'s edge-case table
 * pins down: full-record events (`suggestion.created`/`.updated`) apply directly and
 * reconcile by `id`, `suggestion.deleted` removes by `id`, and a WS disconnect's `resync`
 * triggers a refetch.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Suggestion } from '../../app/types'

type Handler = (envelope: { type: string; payload: unknown }) => void
const handlers = new Map<string, Set<Handler>>()

vi.mock('../../app/socket', () => ({
  socket: {
    subscribe: (type: string, handler: Handler) => {
      const set = handlers.get(type) ?? new Set<Handler>()
      set.add(handler)
      handlers.set(type, set)
      return () => set.delete(handler)
    },
  },
}))

function emit(type: string, payload: unknown) {
  for (const handler of handlers.get(type) ?? []) handler({ type, payload })
}

const list = vi.fn()
const read = vi.fn()
vi.mock('./api', () => ({
  suggestionsApi: {
    list: (...args: unknown[]) => list(...args),
    read: (...args: unknown[]) => read(...args),
  },
}))

const { useSuggestionList } = await import('./useSuggestions')

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

describe('useSuggestionList', () => {
  beforeEach(() => {
    list.mockReset()
    read.mockReset()
    handlers.clear()
  })

  it('loads the initial list from the params it is given', async () => {
    list.mockResolvedValueOnce([suggestion()])
    const { result } = renderHook(() => useSuggestionList({ trip_id: 't1' }))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.suggestions).toHaveLength(1)
    expect(list).toHaveBeenCalledWith({ trip_id: 't1' })
  })

  it('applies suggestion.created directly, reconciled by id — no refetch needed', async () => {
    list.mockResolvedValueOnce([])
    const { result } = renderHook(() => useSuggestionList({ trip_id: 't1' }))
    await waitFor(() => expect(result.current.loading).toBe(false))

    // The real broadcast nests the record under `suggestion` (`_broadcast` calls in
    // `server/app/routers/suggestions.py`) — a flattened mock here is exactly the mismatch
    // the M3 integration pass's live Playwright smoke found (the old flattened cast made
    // `suggestion?.id` always `undefined`, so the event silently did nothing).
    act(() => emit('suggestion.created', { suggestion: suggestion({ id: 'new-1' }) }))
    await waitFor(() => expect(result.current.suggestions.map((s) => s.id)).toContain('new-1'))
    expect(list).toHaveBeenCalledTimes(1) // no refetch triggered
  })

  it('is idempotent: the echo of one\'s own optimistic create does not duplicate the row', async () => {
    list.mockResolvedValueOnce([])
    const { result } = renderHook(() => useSuggestionList({ trip_id: 't1' }))
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.upsert(suggestion({ id: 'opt-1' })))
    act(() => emit('suggestion.created', { suggestion: suggestion({ id: 'opt-1', title: 'Confirmed title' }) }))

    await waitFor(() => expect(result.current.suggestions).toHaveLength(1))
    expect(result.current.suggestions[0].title).toBe('Confirmed title')
  })

  it('removes the row on suggestion.deleted', async () => {
    list.mockResolvedValueOnce([suggestion({ id: 's1' })])
    const { result } = renderHook(() => useSuggestionList({ trip_id: 't1' }))
    await waitFor(() => expect(result.current.suggestions).toHaveLength(1))

    act(() => emit('suggestion.deleted', { id: 's1' }))
    await waitFor(() => expect(result.current.suggestions).toHaveLength(0))
  })

  it('patches status in place on suggestion.status_changed', async () => {
    list.mockResolvedValueOnce([suggestion({ id: 's1', status: 'proposed' })])
    const { result } = renderHook(() => useSuggestionList({ trip_id: 't1' }))
    await waitFor(() => expect(result.current.suggestions).toHaveLength(1))

    act(() => emit('suggestion.status_changed', { id: 's1', status: 'approved' }))
    await waitFor(() => expect(result.current.suggestions[0].status).toBe('approved'))
  })

  it('patches the one family row in place on distance.updated, without a refetch (distances Phase 9)', async () => {
    list.mockResolvedValueOnce([
      suggestion({
        id: 's1',
        distances: [
          { family_id: 'fam-a', family_name: 'Parkers', family_color: 1, status: 'pending', duration_s: null, distance_m: 48_000, is_estimate: true, computed_at: null },
          { family_id: 'fam-b', family_name: 'Hendersons', family_color: 2, status: 'pending', duration_s: null, distance_m: 20_000, is_estimate: true, computed_at: null },
        ],
      }),
    ])
    const { result } = renderHook(() => useSuggestionList({ trip_id: 't1' }))
    await waitFor(() => expect(result.current.suggestions).toHaveLength(1))

    act(() =>
      emit('distance.updated', {
        suggestion_id: 's1',
        family_id: 'fam-a',
        status: 'ok',
        duration_s: 9600,
        distance_m: 210_000,
        is_estimate: false,
        computed_at: '2027-01-02T00:00:00Z',
      }),
    )

    await waitFor(() => {
      const patched = result.current.suggestions[0].distances.find((d) => d.family_id === 'fam-a')
      expect(patched?.status).toBe('ok')
      expect(patched?.duration_s).toBe(9600)
    })
    // The sibling family's still-pending row is untouched — this is a per-row patch, not a
    // whole-suggestion refetch.
    const other = result.current.suggestions[0].distances.find((d) => d.family_id === 'fam-b')
    expect(other?.status).toBe('pending')
    expect(list).toHaveBeenCalledTimes(1) // no refetch triggered
    expect(read).not.toHaveBeenCalled()
  })

  it('reverts real distances to the estimate state on suggestion.moved (D5)', async () => {
    list.mockResolvedValueOnce([
      suggestion({
        id: 's1',
        lat: 50.4,
        lng: -4.7,
        distances: [
          { family_id: 'fam-a', family_name: 'Parkers', family_color: 1, status: 'ok', duration_s: 9600, distance_m: 210_000, is_estimate: false, computed_at: '2027-01-01T00:00:00Z' },
        ],
      }),
    ])
    const { result } = renderHook(() => useSuggestionList({ trip_id: 't1' }))
    await waitFor(() => expect(result.current.suggestions).toHaveLength(1))

    act(() => emit('suggestion.moved', { id: 's1', lat: 51.0, lng: -3.9, geometry_geojson: null }))

    await waitFor(() => {
      const reverted = result.current.suggestions[0].distances[0]
      expect(reverted.status).toBe('pending')
      expect(reverted.duration_s).toBeNull()
      expect(reverted.is_estimate).toBe(true)
    })
    expect(result.current.suggestions[0].lat).toBe(51.0)
  })

  it('refetches and reconciles on resync (reconnect)', async () => {
    list.mockResolvedValueOnce([suggestion({ id: 's1' })])
    const { result } = renderHook(() => useSuggestionList({ trip_id: 't1' }))
    await waitFor(() => expect(result.current.suggestions).toHaveLength(1))

    list.mockResolvedValueOnce([suggestion({ id: 's1' }), suggestion({ id: 's2' })])
    act(() => emit('resync', {}))
    await waitFor(() => expect(result.current.suggestions).toHaveLength(2))
  })
})
