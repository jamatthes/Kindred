/**
 * Pure math for the optimistic vote UI (`design.md` > "Optimistic UI"): apply locally,
 * reconcile with the server's authoritative tally on success, roll back on failure.
 *
 * These functions never invent a number the honesty rules would object to — `count` and
 * `not_voted`/`none` are always kept consistent, and clearing a vote can never make either
 * go negative. They are approximations of what the server will say (the server remains
 * authoritative — the response always replaces this locally-computed guess), which is
 * exactly what "optimistic" means: close enough not to visibly lag, corrected the moment
 * the real answer arrives.
 */

import type { Thumb, VoteTally } from '../../app/types'

function recomputeAverage(distribution: number[]): number | null {
  const total = distribution.reduce((sum, c) => sum + c, 0)
  if (total === 0) return null
  const weighted = distribution.reduce((sum, c, score) => sum + c * score, 0)
  return weighted / total
}

/** Applies a score vote (new, changed, or unchanged) to a tally, optimistically. */
export function applyOptimisticScore(tally: VoteTally, previousScore: number | null, nextScore: number): VoteTally {
  const distribution = (tally.distribution ?? new Array(11).fill(0)).slice()
  if (previousScore !== null) distribution[previousScore] = Math.max(0, distribution[previousScore] - 1)
  distribution[nextScore] = (distribution[nextScore] ?? 0) + 1

  const count = previousScore === null ? tally.count + 1 : tally.count

  return {
    ...tally,
    mode: 'score',
    count,
    distribution,
    average: recomputeAverage(distribution),
    my_vote: { score: nextScore },
    not_voted: previousScore === null ? tally.not_voted : tally.not_voted,
  }
}

/** Clears a score vote, optimistically. */
export function applyOptimisticClearScore(tally: VoteTally, previousScore: number | null): VoteTally {
  if (previousScore === null) return { ...tally, my_vote: null }
  const distribution = (tally.distribution ?? new Array(11).fill(0)).slice()
  distribution[previousScore] = Math.max(0, distribution[previousScore] - 1)
  return {
    ...tally,
    mode: 'score',
    count: Math.max(0, tally.count - 1),
    distribution,
    average: recomputeAverage(distribution),
    my_vote: null,
  }
}

/** Applies a thumbs vote (new, changed, or unchanged), optimistically. `none` — "not yet
 * voted" — is never folded into up/down; it only moves when the voter's own count moves
 * into or out of the voted total. */
export function applyOptimisticThumb(tally: VoteTally, previousThumb: Thumb | null, nextThumb: Thumb): VoteTally {
  let up = tally.up ?? 0
  let down = tally.down ?? 0
  let none = tally.none ?? 0

  if (previousThumb === 'up') up = Math.max(0, up - 1)
  if (previousThumb === 'down') down = Math.max(0, down - 1)
  if (previousThumb === null) none = Math.max(0, none - 1)

  if (nextThumb === 'up') up += 1
  else down += 1

  const count = previousThumb === null ? tally.count + 1 : tally.count

  return { ...tally, mode: 'thumbs', count, up, down, none, my_vote: { thumb: nextThumb } }
}

/** Clears a thumbs vote, optimistically. */
export function applyOptimisticClearThumb(tally: VoteTally, previousThumb: Thumb | null): VoteTally {
  if (previousThumb === null) return { ...tally, my_vote: null }
  let up = tally.up ?? 0
  let down = tally.down ?? 0
  if (previousThumb === 'up') up = Math.max(0, up - 1)
  if (previousThumb === 'down') down = Math.max(0, down - 1)
  const none = (tally.none ?? 0) + 1
  return { ...tally, mode: 'thumbs', count: Math.max(0, tally.count - 1), up, down, none, my_vote: null }
}
