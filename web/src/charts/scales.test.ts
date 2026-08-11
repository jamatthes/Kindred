import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  average,
  clamp,
  clampPref,
  jitter,
  layoutDots,
  linearScale,
  prefRampStep,
  slopeTargetWidth,
} from './scales'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('linearScale', () => {
  it('maps a domain onto a range linearly', () => {
    const scale = linearScale([0, 10], [0, 100])
    expect(scale(0)).toBe(0)
    expect(scale(5)).toBe(50)
    expect(scale(10)).toBe(100)
  })

  it('always starts from the domain minimum, never a shifted baseline', () => {
    // A dataset that never gets near zero still maps 0 -> 0 in the range: there is no
    // way to feed this a non-zero starting point from a chart component.
    const scale = linearScale([0, 10], [0, 200])
    expect(scale(0)).toBe(0)
  })
})

describe('clampPref', () => {
  it('clamps into 0-10', () => {
    expect(clampPref(-3)).toBe(0)
    expect(clampPref(14)).toBe(10)
    expect(clampPref(7)).toBe(7)
  })

  it('logs a development-mode error on out-of-range input, silently in the value returned', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(clampPref(99)).toBe(10)
    // import.meta.env.DEV is true under vitest by default.
    expect(spy).toHaveBeenCalled()
  })
})

describe('prefRampStep', () => {
  it('rounds to the nearest whole ramp step', () => {
    expect(prefRampStep(7.4)).toBe(7)
    expect(prefRampStep(7.6)).toBe(8)
    expect(prefRampStep(-1)).toBe(0)
    expect(prefRampStep(20)).toBe(10)
  })
})

describe('clamp', () => {
  it('bounds a value to [min, max]', () => {
    expect(clamp(5, 0, 10)).toBe(5)
    expect(clamp(-5, 0, 10)).toBe(0)
    expect(clamp(50, 0, 10)).toBe(10)
  })
})

describe('average', () => {
  it('averages a list, and treats empty as 0', () => {
    expect(average([1, 2, 3])).toBe(2)
    expect(average([])).toBe(0)
  })
})

describe('jitter', () => {
  it('returns a single zero offset for one point', () => {
    expect(jitter(1, 10)).toEqual([0])
  })

  it('is deterministic and centred around zero', () => {
    const offsets = jitter(3, 10)
    expect(offsets).toEqual([-10, 0, 10])
    // Re-running produces the same layout — no randomness to destabilise snapshots.
    expect(jitter(3, 10)).toEqual(offsets)
  })
})

describe('layoutDots', () => {
  it('fans out scores that collide at the same pixel position', () => {
    const scale = linearScale([0, 10], [0, 200])
    const positions = layoutDots([8, 8, 8], scale)
    expect(positions).toHaveLength(3)
    const dys = positions.map((p) => p.dy)
    // All three collide on x, so they must not all share the same dy.
    expect(new Set(dys).size).toBe(3)
    expect(positions.every((p) => p.x === positions[0].x)).toBe(true)
  })

  it('does not jitter scores that land on distinct positions', () => {
    const scale = linearScale([0, 10], [0, 200])
    const positions = layoutDots([1, 9], scale)
    expect(positions[0].dy).toBe(0)
    expect(positions[1].dy).toBe(0)
  })
})

describe('slopeTargetWidth', () => {
  it('returns the minimum step width for fewer than two points', () => {
    expect(slopeTargetWidth([5], 40, 8)).toBe(8)
    expect(slopeTargetWidth([], 40, 8)).toBe(8)
  })

  it('stretches wider for a more volatile series than a flat one of the same length', () => {
    const flat = slopeTargetWidth([5, 5, 5, 5, 5], 40, 4)
    const volatile = slopeTargetWidth([0, 10, 0, 10, 0], 40, 4)
    expect(volatile).toBeGreaterThan(flat)
  })
})
