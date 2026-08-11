/**
 * Maps a region's 0–10 preference score to the shared `--scale-pref-N` ramp class, reusing
 * `charts/scales.ts`'s `prefRampStep` — the same rounding rule the poll `HeatMatrix` uses,
 * so a region's map tint and its cell in the score matrix agree on which step a given
 * average lands on (`plan/design-system.md`: "ramp ... reused by map tints, table heat
 * cells, and chart fills so all three views read identically").
 */

import { prefRampStep } from '../../charts/scales'

/** `null`/`undefined` → no poll/vote score exists yet: the neutral, non-scored tint. */
export type PrefTintClass = `k-region--pref-${number}` | 'k-region--neutral'

export function prefTintClass(score: number | null | undefined): PrefTintClass {
  if (score === null || score === undefined) return 'k-region--neutral'
  return `k-region--pref-${prefRampStep(score)}`
}
