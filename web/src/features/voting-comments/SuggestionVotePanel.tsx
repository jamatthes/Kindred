/**
 * SuggestionVotePanel — wires `useCategoryMode` + `useVoteTally` to the presentational vote
 * controls and tally widget, at whatever density the caller needs. This is the one place
 * that decides mode (score vs thumbs) and owns the optimistic-apply/rollback/toast cycle
 * (`design.md` > "Optimistic UI"), so the list row, popover card, and side panel — three
 * different call sites — cannot drift on how a vote actually gets cast.
 *
 * `canVote` gates the input only; the tally itself is always shown (v1: view is universal
 * per the permission table, voting is member-only, both already enforced server-side —
 * this is presentation, not the guard).
 */

import { useEffect, useRef } from 'react'
import { Banner } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import type { SuggestionType } from '../../app/types'
import { useCategoryMode } from './useCategoryMode'
import { useVoteTally } from './useVotes'
import { ScoreVoteControl } from './ScoreVoteControl'
import { ThumbsVoteControl } from './ThumbsVoteControl'
import { VoteTally } from './VoteTally'
import type { VoteTallyDensity } from './VoteTally'
import './voting.css'

export type SuggestionVotePanelProps = {
  suggestionId: string
  suggestionType: SuggestionType
  title: string
  density: VoteTallyDensity
  /** Renders the input control. False for read-only surfaces (e.g. an unauthenticated or
   * frozen-stage view) — the tally still renders. */
  canVote: boolean
  controlSize?: 'compact' | 'full'
}

export function SuggestionVotePanel({
  suggestionId,
  suggestionType,
  title,
  density,
  canVote,
  controlSize = 'full',
}: SuggestionVotePanelProps) {
  const { mode, refetch: refetchMode } = useCategoryMode(suggestionType)
  const { tally, error, pending, vote, clearVote } = useVoteTally(suggestionId)
  const toast = useToast()
  // Toasts are for the user's *own* action's transient confirmation/failure — fire once per
  // error, not on every re-render while `error` stays set.
  const lastToastedError = useRef<string | null>(null)

  useEffect(() => {
    if (error && error !== lastToastedError.current) {
      lastToastedError.current = error
      toast(error)
      // `design.md`'s edge case names a stale mode as the likely cause of a failed vote
      // ("the client refetches settings in case it was stale"); `useVoteTally` normalises
      // every failure to this one string rather than surfacing the raw `ApiError`, so this
      // refetches on any vote failure — cheap, and correct for the case it is aimed at.
      void refetchMode()
    }
    if (!error) lastToastedError.current = null
  }, [error, toast, refetchMode])

  return (
    <div className="svp" data-density={density}>
      <VoteTally tally={tally} density={density} title={title} />
      {canVote ? (
        mode === 'score' ? (
          <ScoreVoteControl
            value={tally?.my_vote?.score ?? null}
            onChange={(v) => void vote(v)}
            disabled={pending || !tally}
            size={controlSize}
          />
        ) : (
          <ThumbsVoteControl
            value={tally?.my_vote?.thumb ?? null}
            onChange={(v) => void vote(v)}
            onClear={() => void clearVote()}
            disabled={pending || !tally}
            size={controlSize}
          />
        )
      ) : null}
      {error && density === 'full' ? <Banner tone="error">{error}</Banner> : null}
    </div>
  )
}
