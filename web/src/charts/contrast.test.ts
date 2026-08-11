import { describe, expect, it } from 'vitest'
import { aaLevel, contrastRatio, relativeLuminance } from './contrast'

describe('relativeLuminance', () => {
  it('is 0 for black and 1 for white', () => {
    expect(relativeLuminance([0, 0, 0])).toBeCloseTo(0, 5)
    expect(relativeLuminance([255, 255, 255])).toBeCloseTo(1, 5)
  })
})

// This suite feeds literal colour strings into the parser under test, which is exactly
// what it exists to check — every literal below is data for `contrastRatio`, not a
// component styling itself with one. `token-check-ignore` per line, deliberately, per
// the exemption documented in scripts/check-tokens.mjs.
describe('contrastRatio', () => {
  it('is 21:1 for black on white', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0) // token-check-ignore
  })

  it('is 1:1 for identical colours', () => {
    expect(contrastRatio('#2D2A26', '#2D2A26')).toBeCloseTo(1, 5) // token-check-ignore
  })

  it('is symmetric', () => {
    const a = contrastRatio('#2D2A26', '#FAF7F2') // token-check-ignore
    const b = contrastRatio('#FAF7F2', '#2D2A26') // token-check-ignore
    expect(a).toBeCloseTo(b!, 10)
  })

  it('parses the functional notation and short hex, and returns null for anything else', () => {
    expect(contrastRatio('rgb(0, 0, 0)', 'rgb(255, 255, 255)')).toBeCloseTo(21, 0) // token-check-ignore
    expect(contrastRatio('#fff', '#000')).toBeCloseTo(21, 0) // token-check-ignore
    expect(contrastRatio('not-a-colour', '#000')).toBeNull() // token-check-ignore
    expect(contrastRatio('var(--unresolved)', '#000')).toBeNull() // token-check-ignore
  })
})

describe('aaLevel', () => {
  it('passes AA at 4.5:1 or above', () => {
    expect(aaLevel(4.5)).toBe('AA')
    expect(aaLevel(7)).toBe('AA')
  })

  it('passes only at the large-text/UI threshold between 3 and 4.5, when asked', () => {
    expect(aaLevel(3.2, true)).toBe('AA-large')
    expect(aaLevel(3.2, false)).toBe('fail')
  })

  it('fails below 3:1, and fails an unresolved (null) ratio rather than passing it silently', () => {
    expect(aaLevel(2.9, true)).toBe('fail')
    expect(aaLevel(null)).toBe('fail')
  })
})
