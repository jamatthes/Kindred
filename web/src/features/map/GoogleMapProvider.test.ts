/**
 * `toBase64Utf8` — regression coverage for a real, reproducible crash the M3 integration
 * pass's live Playwright smoke found: `suggestionIcon()` builds a marker's SVG with a
 * `STATUS_GLYPH` character ('★'/'✓'/'✕'/'▸', all outside Latin-1) and used to hand that
 * straight to `btoa`, which throws `InvalidCharacterError` on anything past code point
 * 0xFF. Because a suggestion's marker is rendered on every map load, this meant approving
 * (or shortlisting/rejecting/scheduling) even one suggestion permanently broke the map for
 * every viewer afterwards — with no `ErrorBoundary` anywhere in the app, the whole page
 * went blank rather than just the marker failing to render.
 */
import { describe, expect, it } from 'vitest'
import { toBase64Utf8 } from './GoogleMapProvider'
import { STATUS_GLYPH } from './SuggestionPin'

describe('toBase64Utf8', () => {
  it('round-trips plain ASCII exactly like a bare btoa would', () => {
    expect(atob(toBase64Utf8('hello world'))).toBe('hello world')
  })

  it('does not throw on every STATUS_GLYPH value, and round-trips each one', () => {
    for (const glyph of Object.values(STATUS_GLYPH)) {
      const svg = `<svg><text>${glyph}</text></svg>`
      expect(() => toBase64Utf8(svg)).not.toThrow()
      // Decoding the Latin-1 bytes back through the same UTF-8-aware path recovers the
      // original string — proof this isn't merely "doesn't throw" but actually correct.
      const decoded = decodeURIComponent(escape(atob(toBase64Utf8(svg))))
      expect(decoded).toBe(svg)
    }
  })

  it('a bare btoa would have thrown on these same glyphs (documents the bug this replaces)', () => {
    const nonLatin1Glyphs = Object.values(STATUS_GLYPH).filter((g) => [...g].some((c) => c.codePointAt(0)! > 0xff))
    expect(nonLatin1Glyphs.length).toBeGreaterThan(0)
    for (const glyph of nonLatin1Glyphs) {
      expect(() => btoa(glyph)).toThrow()
    }
  })
})
