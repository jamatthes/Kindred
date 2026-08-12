import { describe, expect, it } from 'vitest'
import { distanceForFamily, distanceSortValue } from './distanceOrder'
import type { DistanceOut } from '../../app/types'

function d(overrides: Partial<DistanceOut> = {}): DistanceOut {
  return {
    family_id: 'f1',
    family_name: 'Parkers',
    family_color: 1,
    status: 'ok',
    duration_s: 3600,
    distance_m: 50_000,
    is_estimate: false,
    computed_at: '2027-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('distanceSortValue — tiering', () => {
  it('orders real < estimate < failed/no_home < no_route, regardless of raw numbers', () => {
    const real = distanceSortValue(d({ status: 'ok', duration_s: 999_999 }))
    const estimate = distanceSortValue(d({ status: 'pending', duration_s: null, distance_m: 1 }))
    const failed = distanceSortValue(d({ status: 'failed', duration_s: null, distance_m: null }))
    const noHome = distanceSortValue(d({ status: 'no_home', duration_s: null, distance_m: null }))
    const noRoute = distanceSortValue(d({ status: 'no_route', duration_s: null, distance_m: null }))

    expect(real).toBeLessThan(estimate)
    expect(estimate).toBeLessThan(failed)
    expect(failed).toBeLessThan(noRoute)
    // failed and no_home are the same tier — order between them is not meaningful.
    expect(Math.floor(failed / 10_000_000)).toBe(Math.floor(noHome / 10_000_000))
  })

  it('within the real tier, shorter durations sort first', () => {
    const near = distanceSortValue(d({ status: 'ok', duration_s: 1800 }))
    const far = distanceSortValue(d({ status: 'ok', duration_s: 7200 }))
    expect(near).toBeLessThan(far)
  })

  it('within the estimate tier, shorter distances sort first', () => {
    const near = distanceSortValue(d({ status: 'pending', duration_s: null, distance_m: 5000 }))
    const far = distanceSortValue(d({ status: 'pending', duration_s: null, distance_m: 500_000 }))
    expect(near).toBeLessThan(far)
  })

  it('a missing distance (no row at all) sorts with the unavailable tier', () => {
    expect(distanceSortValue(null)).toBe(distanceSortValue(d({ status: 'failed', duration_s: null, distance_m: null })))
  })
})

describe('distanceForFamily', () => {
  it('finds the row for the requested family id', () => {
    const rows = [d({ family_id: 'a' }), d({ family_id: 'b' })]
    expect(distanceForFamily(rows, 'b')?.family_id).toBe('b')
  })

  it('returns null when that family has no row', () => {
    expect(distanceForFamily([d({ family_id: 'a' })], 'z')).toBeNull()
  })
})
