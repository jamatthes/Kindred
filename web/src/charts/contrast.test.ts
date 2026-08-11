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

// Regression guard for the four light-theme AA failures the styleguide's live readout
// found (jsdom does not resolve chained CSS custom properties — see StyleguideTokens.tsx
// — so this is the only place these specific token *values* can be locked in by an
// automated test; the styleguide readout itself is still the source of truth in a real
// browser). Every literal here is the current tokens.semantic.css / tokens.primitives.css
// light-theme value it names — update both together if either changes.
describe('light-theme token contrast (design-system contrast fixes)', () => {
  it('white text on --color-accent (primary button labels, wordmark) clears AA', () => {
    const ratio = contrastRatio('#FFFFFF', '#D1452A') // token-check-ignore
    expect(ratio).not.toBeNull()
    expect(ratio!).toBeGreaterThanOrEqual(4.5)
  })

  it('--color-success on --color-success-soft clears AA', () => {
    const ratio = contrastRatio('#2A7B3B', '#E4F2E7') // token-check-ignore
    expect(ratio!).toBeGreaterThanOrEqual(4.5)
  })

  it('--color-warning on --color-warning-soft clears AA', () => {
    const ratio = contrastRatio('#B05109', '#F8EEDD') // token-check-ignore
    expect(ratio!).toBeGreaterThanOrEqual(4.5)
  })

  it('--color-info on --color-info-soft clears AA', () => {
    const ratio = contrastRatio('#2160EB', '#E4EDFC') // token-check-ignore
    expect(ratio!).toBeGreaterThanOrEqual(4.5)
  })

  it('--color-danger on --color-danger-soft still clears AA, unchanged by this fix', () => {
    const ratio = contrastRatio('#B91C1C', '#F9E5E5') // token-check-ignore
    expect(ratio!).toBeGreaterThanOrEqual(4.5)
  })
})

// Same regression guard as above, for the dark-theme AA failure the readout found next:
// --color-danger (--red-400) on --color-danger-soft was 4.48:1. Literals mirror the
// current dark-theme values in tokens.semantic.css / tokens.primitives.css — update both
// together if either changes.
describe('dark-theme token contrast (design-system contrast fixes)', () => {
  it('--color-danger on --color-danger-soft clears AA', () => {
    const ratio = contrastRatio('#E5786D', '#422A28') // token-check-ignore
    expect(ratio).not.toBeNull()
    expect(ratio!).toBeGreaterThanOrEqual(4.5)
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
