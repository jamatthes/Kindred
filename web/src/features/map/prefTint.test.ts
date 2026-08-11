import { describe, expect, it } from 'vitest'
import { prefTintClass } from './prefTint'

describe('prefTintClass', () => {
  it('is neutral when no score exists yet', () => {
    expect(prefTintClass(null)).toBe('k-region--neutral')
    expect(prefTintClass(undefined)).toBe('k-region--neutral')
  })

  it('rounds to the nearest ramp step, matching HeatMatrix', () => {
    expect(prefTintClass(0)).toBe('k-region--pref-0')
    expect(prefTintClass(10)).toBe('k-region--pref-10')
    expect(prefTintClass(8.2)).toBe('k-region--pref-8')
    expect(prefTintClass(8.6)).toBe('k-region--pref-9')
  })

  it('clamps out-of-range scores rather than producing an invalid class', () => {
    expect(prefTintClass(-3)).toBe('k-region--pref-0')
    expect(prefTintClass(15)).toBe('k-region--pref-10')
  })
})
