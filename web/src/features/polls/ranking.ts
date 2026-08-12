/**
 * Ordering the results by the server's own rank.
 *
 * A module of its own rather than an export beside a component: React Fast Refresh only
 * works when a file exports components alone, and every view that shows options — bars,
 * spread, matrix, decision dialog — needs the same order. Sorting locally by average would
 * be a second ranking implementation that could disagree with the server's, including on
 * the tie-breaks.
 */

import type { OptionResult, PollResults } from '../../app/types'

export function optionsByRank(results: PollResults | null): OptionResult[] {
  return [...(results?.options ?? [])].sort((a, b) => a.rank - b.rank)
}
