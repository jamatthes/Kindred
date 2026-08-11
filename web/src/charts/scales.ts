/**
 * Small scale + preference-ramp helpers shared by the chart widgets.
 *
 * No d3, no chart library (`CLAUDE.md`) — these are a handful of linear maps that do not
 * warrant a dependency.
 */

const PREF_MIN = 0
const PREF_MAX = 10

/**
 * Clamps a preference score into the valid 0–10 range. Per the edge-case table in
 * `plan/features/design-system/design.md`: silent clamp in production, a loud
 * development-mode console error so an out-of-range value is caught before it ships.
 */
export function clampPref(value: number): number {
  const clamped = Math.min(PREF_MAX, Math.max(PREF_MIN, value))
  if (clamped !== value && import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.error(`[charts] preference value ${value} is out of range 0–10; clamped to ${clamped}`)
  }
  return clamped
}

/**
 * The CSS custom property backing a given 0–10 preference step, rounded to the nearest
 * whole step (`--scale-pref-0` … `--scale-pref-10`). Consumers combine this with
 * `--mix-tint-strong` via `color-mix()` (see `charts.css`) rather than using the ramp at
 * full saturation, per the existing tint recipe in `tokens.components.css`.
 */
export function prefRampStep(value: number): number {
  return Math.round(clampPref(value))
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export type Scale = (value: number) => number

/**
 * A linear map from a numeric domain to a pixel range. This is bar/dot geometry only —
 * it is never used to fake a non-zero baseline. Callers that need a zero-based bar pass
 * `[0, max]` as the domain themselves; there is no `baseline` prop anywhere that could
 * feed something else in here.
 */
export function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0 || 1
  return (value: number) => r0 + ((value - d0) / span) * (r1 - r0)
}

export function average(values: number[]): number {
  if (values.length === 0) return 0
  return values.reduce((sum, v) => sum + v, 0) / values.length
}

/**
 * Deterministic (index-based, not random) perpendicular offsets for `count` points that
 * would otherwise collide at the same position — used by `SpreadDots` to fan overlapping
 * scores apart instead of hiding them. Deterministic so snapshots and repeated renders
 * are stable.
 */
export function jitter(count: number, spacing: number): number[] {
  if (count <= 1) return [0]
  const span = (count - 1) * spacing
  return Array.from({ length: count }, (_, i) => i * spacing - span / 2)
}

/**
 * Groups scores that round to the same pixel position on `scale` and fans each group out
 * with `jitter`, so `SpreadDots` never silently stacks two members' dots into one.
 */
export function layoutDots(
  scores: number[],
  scale: Scale,
  dotSpacing = 12,
): { x: number; dy: number }[] {
  const buckets = new Map<number, number[]>()
  const order: number[] = []
  scores.forEach((score, index) => {
    const x = Math.round(scale(clampPref(score)))
    if (!buckets.has(x)) {
      buckets.set(x, [])
      order.push(x)
    }
    buckets.get(x)!.push(index)
  })

  const result: { x: number; dy: number }[] = new Array(scores.length)
  for (const x of order) {
    const indices = buckets.get(x)!
    const offsets = jitter(indices.length, dotSpacing)
    indices.forEach((scoreIndex, i) => {
      result[scoreIndex] = { x, dy: offsets[i] }
    })
  }
  return result
}

/**
 * Picks a chart width that targets a ~45° average trend slope for a time series, per
 * honesty rule 3 in `plan/design-system.md`. A flat series gets a compact width; a
 * volatile one is stretched out so the eye doesn't over-read noise as drama, or under-read
 * a real swing as noise.
 */
export function slopeTargetWidth(values: number[], height: number, minStep: number): number {
  const n = values.length
  if (n < 2) return minStep
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const rises: number[] = []
  for (let i = 1; i < n; i++) {
    rises.push((Math.abs(values[i] - values[i - 1]) / range) * height)
  }
  const meanRise = average(rises)
  const stepWidth = Math.max(meanRise, minStep)
  return stepWidth * (n - 1)
}
