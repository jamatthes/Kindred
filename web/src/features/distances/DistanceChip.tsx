/**
 * DistanceChip — the five-state distance readout (`design.md` > "Distance chips").
 *
 * **Deliberately does not use the preference ramp (`--scale-pref-0…10`).** That ramp means
 * "how much the group likes this"; reusing it for "how far away this is" would make two
 * unrelated meanings look identical on a card, which is the one thing `design.md` calls out
 * by name. `DistanceChip.test.tsx` asserts this by reading both the rendered DOM and this
 * file's own CSS source for the token substring.
 *
 * Every state pairs colour with text and an icon — never colour alone — and duration comes
 * first when there is one, because duration is what people actually plan a drive around.
 */

import { formatDistanceMeters, formatDuration } from './format'
import type { DistanceOut } from '../../app/types'
import './distances.css'

function CarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M5 11l1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11" />
      <rect x="3" y="11" width="18" height="6" rx="1.5" />
      <circle cx="7.5" cy="17" r="1.6" />
      <circle cx="16.5" cy="17" r="1.6" />
    </svg>
  )
}

function RulerIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M4 16l8-8M4 16l4 4L20 8l-4-4L4 16Z" />
      <path d="M9 11l1.5 1.5M12.5 7.5 14 9" />
    </svg>
  )
}

function FerryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M4 15l1.5 5h13L20 15" />
      <path d="M6 15V8h12v7M9 8V5h6v3" />
      <path d="M2 19c1.5 1 3 1 4.5 0s3-1 4.5 0 3 1 4.5 0 3-1 4.5 0" />
    </svg>
  )
}

function WarningIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M12 3 2 20h20L12 3Z" />
      <path d="M12 9v5M12 17h.01" />
    </svg>
  )
}

function HomeQuestionIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M3 11l9-7 9 7" />
      <path d="M5 10v10h5v-5h4v5h5V10" />
      <path d="M12 8.5v-.2" />
    </svg>
  )
}

export type DistanceChipProps = {
  distance: DistanceOut
  /** Regions measure to their geometry's centroid — the tooltip states the approximation. */
  isRegion?: boolean
  /** Organiser-only: a `failed` chip additionally offers a retry. */
  canRetry?: boolean
  onRetry?: () => void
  /** `no_home`: a link for that family's own head/spouse (or an organiser) to set it. */
  onSetHome?: () => void
  /** Suppresses the estimate→real crossfade — used where the parent already handles its own
   *  transition (e.g. a list cell that re-renders wholesale). Defaults to on. */
  animate?: boolean
}

const REGION_SUFFIX = ' to the centre of this region.'

export function DistanceChip({ distance, isRegion = false, canRetry = false, onRetry, onSetHome, animate = true }: DistanceChipProps) {
  const name = distance.family_name

  if (distance.status === 'no_home') {
    return (
      <span className="dist-chip dist-chip--no_home" title="This family has not set a home address yet.">
        <HomeQuestionIcon />
        <span className="dist-chip__text">Home address not set</span>
        {onSetHome ? (
          <button type="button" className="dist-chip__action" onClick={onSetHome}>
            Set it
          </button>
        ) : null}
      </span>
    )
  }

  if (distance.status === 'no_route') {
    return (
      <span
        className="dist-chip dist-chip--no_route"
        title={`No driving route exists — a ferry or flight may be needed.${isRegion ? REGION_SUFFIX : ''}`}
      >
        <FerryIcon />
        <span className="dist-chip__text">No driving route from {name}</span>
      </span>
    )
  }

  if (distance.status === 'failed') {
    return (
      <span className="dist-chip dist-chip--failed" title="The distance service could not answer for this pair.">
        <WarningIcon />
        <span className="dist-chip__text">Distance unavailable</span>
        {canRetry && onRetry ? (
          <button type="button" className="dist-chip__action" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </span>
    )
  }

  if (distance.status === 'ok' && distance.duration_s !== null) {
    return (
      <span className={`dist-chip dist-chip--ok${animate ? ' dist-chip--animated' : ''}`} title={`Driving time from ${name}.`}>
        <CarIcon />
        <span className="dist-chip__text tabular">
          {formatDuration(distance.duration_s)} from {name}
        </span>
      </span>
    )
  }

  // `pending` (or an `ok` row somehow missing a duration — treated the same, defensively):
  // the haversine estimate. Distance only, never a fabricated duration.
  return (
    <span
      className={`dist-chip dist-chip--estimate${animate ? ' dist-chip--animated' : ''}`}
      title={`A straight-line estimate is shown until the driving time is calculated.${isRegion ? REGION_SUFFIX : ''}`}
    >
      <RulerIcon />
      <span className="dist-chip__text tabular">
        {distance.distance_m !== null ? `~${formatDistanceMeters(distance.distance_m)} from ${name}` : `Distance from ${name} pending`}
        <span className="dist-chip__approx"> · driving time pending</span>
      </span>
    </span>
  )
}
