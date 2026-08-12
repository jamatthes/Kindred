import { describe, expect, it } from 'vitest'
import {
  applyOptimisticClearScore,
  applyOptimisticClearThumb,
  applyOptimisticScore,
  applyOptimisticThumb,
} from './voteMath'
import type { VoteTally } from '../../app/types'

function scoreTally(overrides: Partial<VoteTally> = {}): VoteTally {
  return {
    mode: 'score',
    count: 2,
    eligible_count: 5,
    average: 6,
    distribution: [0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0], // scores 4 and 6
    up: null,
    down: null,
    none: null,
    my_vote: null,
    voters: [],
    not_voted: [],
    ...overrides,
  }
}

function thumbsTally(overrides: Partial<VoteTally> = {}): VoteTally {
  return {
    mode: 'thumbs',
    count: 2,
    eligible_count: 5,
    average: null,
    distribution: null,
    up: 1,
    down: 1,
    none: 3,
    my_vote: null,
    voters: [],
    not_voted: [],
    ...overrides,
  }
}

describe('applyOptimisticScore', () => {
  it('increments count for a first-time vote and recomputes the average honestly', () => {
    const next = applyOptimisticScore(scoreTally(), null, 10)
    expect(next.count).toBe(3)
    expect(next.my_vote).toEqual({ score: 10 })
    // (4 + 6 + 10) / 3
    expect(next.average).toBeCloseTo(20 / 3, 5)
  })

  it('does not change count when replacing an existing vote', () => {
    const next = applyOptimisticScore(scoreTally(), 4, 8)
    expect(next.count).toBe(2) // unchanged: a change, not a new voter
    expect(next.average).toBe((8 + 6) / 2)
  })
})

describe('applyOptimisticClearScore', () => {
  it('decrements count and never lets it go negative', () => {
    const empty = scoreTally({ count: 0, distribution: new Array(11).fill(0) })
    const next = applyOptimisticClearScore(empty, null)
    expect(next.count).toBe(0)
    expect(next.my_vote).toBeNull()
  })

  it('recomputes average as null rather than 0 when the last vote is cleared', () => {
    const single = scoreTally({ count: 1, distribution: [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0], average: 4 })
    const next = applyOptimisticClearScore(single, 4)
    expect(next.count).toBe(0)
    expect(next.average).toBeNull() // never a misleading 0.0
  })
})

describe('applyOptimisticThumb', () => {
  it('a first-time up vote increments count and up, and decrements none', () => {
    const next = applyOptimisticThumb(thumbsTally(), null, 'up')
    expect(next.count).toBe(3)
    expect(next.up).toBe(2)
    expect(next.none).toBe(2)
    expect(next.my_vote).toEqual({ thumb: 'up' })
  })

  it('changing from down to up moves the count between buckets without touching total', () => {
    const next = applyOptimisticThumb(thumbsTally(), 'down', 'up')
    expect(next.count).toBe(2) // unchanged
    expect(next.up).toBe(2)
    expect(next.down).toBe(0)
    expect(next.none).toBe(3) // untouched — this voter was already counted
  })
})

describe('applyOptimisticClearThumb', () => {
  it('moves the voter back into "not voted" (none), never fabricating a value', () => {
    const next = applyOptimisticClearThumb(thumbsTally(), 'up')
    expect(next.count).toBe(1)
    expect(next.up).toBe(0)
    expect(next.none).toBe(4)
    expect(next.my_vote).toBeNull()
  })

  it('is a no-op on count/up/down when there was nothing to clear', () => {
    const tally = thumbsTally()
    const next = applyOptimisticClearThumb(tally, null)
    expect(next.count).toBe(tally.count)
    expect(next.up).toBe(tally.up)
    expect(next.down).toBe(tally.down)
  })
})
