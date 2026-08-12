/**
 * PendingVotesChip — "N need your vote" in the trip chrome (V5). Activating it toggles the
 * shared `needsMyVote` filter (`map-suggestions/store.ts`), which narrows the suggestion
 * list/map to `GET /me/pending-votes`'s id set. Zero state stays visible but quiet ("You're
 * all caught up") rather than disappearing, per `design.md`.
 */

import { usePendingVotes } from './usePendingVotes'
import { suggestionStore, useSuggestionView } from '../map-suggestions/store'
import './voting.css'

export function PendingVotesChip({ tripId }: { tripId: string | null }) {
  const pending = usePendingVotes(tripId)
  const view = useSuggestionView()

  return (
    <button
      type="button"
      className={`pending-votes-chip${view.filters.needsMyVote ? ' is-on' : ''}`}
      aria-pressed={view.filters.needsMyVote}
      onClick={() => suggestionStore.toggleNeedsMyVote()}
    >
      {pending.count > 0 ? (
        <>
          <span className="pending-votes-chip__count tabular">{pending.count}</span>
          <span>need{pending.count === 1 ? 's' : ''} your vote</span>
        </>
      ) : (
        <span>You&apos;re all caught up</span>
      )}
    </button>
  )
}
