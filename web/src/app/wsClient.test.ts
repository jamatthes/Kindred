import { describe, expect, it } from 'vitest'
import { backoffDelay, socketUrl } from './wsClient'

describe('socket backoff', () => {
  it('starts at a second and never exceeds thirty', () => {
    for (let attempt = 1; attempt <= 20; attempt++) {
      const min = backoffDelay(attempt, () => 0)
      const max = backoffDelay(attempt, () => 1)
      expect(min).toBe(1_000)
      expect(max).toBeLessThanOrEqual(30_000)
      expect(max).toBeGreaterThanOrEqual(min)
    }
  })

  it('grows the ceiling exponentially until the cap', () => {
    expect(backoffDelay(1, () => 1)).toBe(1_000)
    expect(backoffDelay(2, () => 1)).toBe(2_000)
    expect(backoffDelay(3, () => 1)).toBe(4_000)
    expect(backoffDelay(6, () => 1)).toBe(30_000)
    expect(backoffDelay(12, () => 1)).toBe(30_000)
  })

  it('jitters within the window rather than firing on the same tick', () => {
    // Full jitter: two clients that failed together must not retry together.
    const early = backoffDelay(5, () => 0.1)
    const late = backoffDelay(5, () => 0.9)
    expect(early).toBeLessThan(late)
  })
})

describe('socketUrl', () => {
  it('is at the root, not under /api/v1, and follows the page protocol', () => {
    expect(socketUrl({ protocol: 'http:', host: 'localhost:5173' } as Location)).toBe(
      'ws://localhost:5173/ws',
    )
    expect(socketUrl({ protocol: 'https:', host: 'kindred.example.org' } as Location)).toBe(
      'wss://kindred.example.org/ws',
    )
  })
})
