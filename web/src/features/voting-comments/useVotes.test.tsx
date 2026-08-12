/**
 * `useVoteTally` — the optimistic-apply/rollback cycle and the WS `my_vote` merge
 * `design.md` > "Optimistic UI" and "WebSocket events" specify.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoteTally } from '../../app/types'

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

const read = vi.fn()
const upsert = vi.fn()
const clear = vi.fn()
vi.mock('./api', () => ({
  votesApi: {
    read: (...args: unknown[]) => read(...args),
    upsert: (...args: unknown[]) => upsert(...args),
    clear: (...args: unknown[]) => clear(...args),
  },
}))

const { useVoteTally } = await import('./useVotes')

function tally(overrides: Partial<VoteTally> = {}): VoteTally {
  return {
    mode: 'score',
    count: 2,
    eligible_count: 5,
    average: 5,
    distribution: [0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0],
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
  upsert.mockReset()
  clear.mockReset()
  handlers.clear()
})

describe('useVoteTally — optimistic apply and rollback', () => {
  it('applies a vote immediately and reconciles with the server response', async () => {
    read.mockResolvedValueOnce(tally())
    const { result } = renderHook(() => useVoteTally('s1'))
    await waitFor(() => expect(result.current.tally).not.toBeNull())

    let resolveUpsert!: (value: VoteTally) => void
    upsert.mockReturnValueOnce(new Promise((resolve) => (resolveUpsert = resolve)))

    act(() => void result.current.vote(9))
    // Optimistic: my_vote shows immediately, before the request resolves.
    await waitFor(() => expect(result.current.tally?.my_vote).toEqual({ score: 9 }))

    resolveUpsert(tally({ count: 3, average: 6.3, my_vote: { score: 9 } }))
    await waitFor(() => expect(result.current.tally?.count).toBe(3))
    expect(result.current.error).toBeNull()
  })

  it('rolls back visibly to the previous tally when the request fails', async () => {
    read.mockResolvedValueOnce(tally({ my_vote: { score: 5 } }))
    const { result } = renderHook(() => useVoteTally('s1'))
    await waitFor(() => expect(result.current.tally).not.toBeNull())
    const before = result.current.tally

    upsert.mockRejectedValueOnce(new Error('nope'))
    await act(async () => {
      await result.current.vote(9)
    })

    // Rolled back: the tally is exactly what it was before the failed attempt.
    expect(result.current.tally).toEqual(before)
    expect(result.current.error).toBe('That vote could not be saved.')
  })
})

describe('useVoteTally — WS merge', () => {
  it('merges the broadcast tally (no my_vote) with the locally-known my_vote', async () => {
    read.mockResolvedValueOnce(tally({ my_vote: { score: 7 } }))
    const { result } = renderHook(() => useVoteTally('s1'))
    await waitFor(() => expect(result.current.tally?.my_vote).toEqual({ score: 7 }))

    act(() =>
      emit('suggestion.vote.updated', {
        suggestion_id: 's1',
        mode: 'score',
        count: 5,
        eligible_count: 5,
        average: 8,
        distribution: null,
        up: null,
        down: null,
        none: null,
        voters: [],
        not_voted: [],
        // Deliberately no my_vote key — the broadcast never carries it.
      }),
    )

    await waitFor(() => expect(result.current.tally?.count).toBe(5))
    // This client's own vote survives the broadcast merge untouched.
    expect(result.current.tally?.my_vote).toEqual({ score: 7 })
  })

  it('ignores a vote-updated event for a different suggestion', async () => {
    read.mockResolvedValueOnce(tally())
    const { result } = renderHook(() => useVoteTally('s1'))
    await waitFor(() => expect(result.current.tally).not.toBeNull())

    act(() => emit('suggestion.vote.updated', { suggestion_id: 'other', count: 99 }))
    expect(result.current.tally?.count).not.toBe(99)
  })
})
