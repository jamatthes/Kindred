/**
 * WCAG 2.x relative luminance and contrast ratio — pure math, no dependency. Backs the
 * `/styleguide` token gallery's per-pairing contrast readout
 * (`plan/features/design-system/tasks.md` Phase 8: "a contrast readout beside each colour
 * pairing showing the computed ratio and a pass/fail marker" — the thing that makes
 * "checked at token level, once" an actual, repeatable check rather than a one-time claim).
 */

function parseColor(value: string): [number, number, number] | null {
  const v = value.trim()
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(v)
  if (hex) {
    const digits = hex[1]
    const full =
      digits.length === 3
        ? digits
            .split('')
            .map((c) => c + c)
            .join('')
        : digits
    const num = parseInt(full, 16)
    return [(num >> 16) & 255, (num >> 8) & 255, num & 255]
  }
  const rgb = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(v)
  if (rgb) {
    return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])]
  }
  return null
}

function channelLuminance(channel: number): number {
  const s = channel / 255
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

export function relativeLuminance([r, g, b]: [number, number, number]): number {
  return 0.2126 * channelLuminance(r) + 0.7152 * channelLuminance(g) + 0.0722 * channelLuminance(b)
}

/**
 * The WCAG contrast ratio (1–21) between two CSS colour strings — hex, or the functional
 * red/green/blue(/alpha) notation. Returns `null` when either colour can't be parsed —
 * e.g. an unresolved custom property in an environment without full `var()` substitution,
 * such as jsdom under Vitest — so callers show an honest "—" instead of crashing or lying
 * with a fabricated number.
 */
export function contrastRatio(a: string, b: string): number | null {
  const rgbA = parseColor(a)
  const rgbB = parseColor(b)
  if (!rgbA || !rgbB) return null
  const lA = relativeLuminance(rgbA)
  const lB = relativeLuminance(rgbB)
  const lighter = Math.max(lA, lB)
  const darker = Math.min(lA, lB)
  return (lighter + 0.05) / (darker + 0.05)
}

export type AaResult = 'AA' | 'AA-large' | 'fail'

/** 4.5:1 for normal text, 3:1 for large text / UI components — WCAG 2.1 SC 1.4.3 / 1.4.11. */
export function aaLevel(ratio: number | null, large = false): AaResult {
  if (ratio === null) return 'fail'
  if (ratio >= 4.5) return 'AA'
  if (large && ratio >= 3) return 'AA-large'
  return 'fail'
}
