/**
 * PopoverCard — the compact pin-click card, progressive-disclosure level 2 in
 * `plan/features/map-suggestions/design.md`: "Compact and glanceable; no scrolling."
 *
 * Vote summary and distance chips are slots (`ReactNode`), not hardcoded shapes, because
 * their real content — the vote-tally widget, per-family distance chips — belongs to the
 * `voting-comments` and `distances` features (M3), which are not part of this pre-build.
 * `Details` is a callback, never a navigation: the map shell has no opinion on routing.
 */

import type { ReactNode } from 'react'
import type { SuggestionCategory, SuggestionStatus } from './types'
import './PopoverCard.css'

const CATEGORY_LABEL: Record<SuggestionCategory, string> = {
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
  region: 'Region',
}

const STATUS_LABEL: Record<SuggestionStatus, string> = {
  proposed: 'Proposed',
  shortlisted: 'Shortlisted',
  approved: 'Approved',
  rejected: 'Rejected',
  scheduled: 'Scheduled',
}

export type PopoverCardProps = {
  title: string
  category: SuggestionCategory
  status: SuggestionStatus
  /** Vote-tally widget slot — filled by `voting-comments` at M3. */
  voteSummary?: ReactNode
  commentCount?: number
  /** Per-family distance chip row — filled by `distances` at M3. */
  distanceChips?: ReactNode
  onDetails?: () => void
  /** "Open in Google Maps" per the design doc — a plain deep link, not an API call. The
   *  URL itself is the M3 agent's concern (needs `lat`/`lng`/`place_id`); this component
   *  only renders the slot if a handler is supplied. */
  onOpenInMaps?: () => void
}

export function PopoverCard({
  title,
  category,
  status,
  voteSummary,
  commentCount,
  distanceChips,
  onDetails,
  onOpenInMaps,
}: PopoverCardProps) {
  return (
    <div className="k-popover" role="dialog" aria-label={title} data-testid="popover-card">
      <h4 className="k-popover__title">{title}</h4>
      <div className="k-popover__meta">
        <span className="k-popover__chip">{CATEGORY_LABEL[category]}</span>
        <span className={`k-popover__chip k-popover__chip--status-${status}`}>
          {STATUS_LABEL[status]}
        </span>
      </div>

      {voteSummary ? <div className="k-popover__votes">{voteSummary}</div> : null}

      <div className="k-popover__row">
        {commentCount !== undefined ? (
          <span className="k-popover__comments">
            {commentCount} comment{commentCount === 1 ? '' : 's'}
          </span>
        ) : null}
      </div>

      {distanceChips ? <div className="k-popover__distances">{distanceChips}</div> : null}

      <div className="k-popover__actions">
        {onDetails ? (
          <button type="button" className="k-popover__btn k-popover__btn--primary" onClick={onDetails}>
            Details
          </button>
        ) : null}
        {onOpenInMaps ? (
          <button type="button" className="k-popover__btn k-popover__btn--secondary" onClick={onOpenInMaps}>
            Open in Maps
          </button>
        ) : null}
      </div>
    </div>
  )
}
