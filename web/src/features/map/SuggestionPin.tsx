/**
 * SuggestionPin — the map-suggestion pin: type icon, family colour accent, status
 * treatment. Per `plan/features/map-suggestions/design.md` progressive-disclosure level 1.
 *
 * Status is never carried by colour alone: `rejected` also desaturates/mutes the pin and
 * every non-`proposed` status also renders a small glyph badge, so a colourblind viewer or
 * a black-and-white screenshot still reads the state.
 *
 * The classname/icon logic is exported as plain functions so `FakeMapProvider` — which
 * builds real DOM nodes imperatively, not through React — can reuse exactly the same
 * visual vocabulary instead of re-deriving it.
 */

import type { SuggestionCategory, SuggestionMarkerSpec, SuggestionStatus } from './types'
import './SuggestionPin.css'

/** Raw SVG path markup (viewBox `0 0 24 24`), shared between the JSX icon below and
 *  `FakeMapProvider`'s `innerHTML` construction. */
export const CATEGORY_ICON_PATHS: Record<SuggestionCategory, string> = {
  accommodation: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
  activity:
    '<circle cx="12" cy="5" r="2.2"/><path d="M5 22l3-7 4-2 2 4 5 1M9 10l3-3 4 2"/>',
  meal: '<path d="M7 3v8M11 3v8M9 3v18M17 3c-2 1-3 3-3 6v3h4v9"/>',
  region: '<path d="M4 4l8 4 8-4-4 16-4-4-4 4z"/>',
}

/** One-character glyph badges — the non-colour carrier of status. `proposed` is the
 *  baseline state and gets none. */
export const STATUS_GLYPH: Partial<Record<SuggestionStatus, string>> = {
  shortlisted: '★',
  approved: '✓',
  rejected: '✕',
  scheduled: '▸',
}

export function suggestionPinClassName(spec: Pick<SuggestionMarkerSpec, 'status' | 'selected'>): string {
  return [
    'k-pin',
    `k-pin--${spec.status}`,
    spec.selected ? 'is-selected' : '',
  ]
    .filter(Boolean)
    .join(' ')
}

export type SuggestionPinProps = {
  marker: SuggestionMarkerSpec
  onClick?: (id: string) => void
  onHoverChange?: (hovering: boolean) => void
  /** Accessible name — the pin's title, e.g. the suggestion's title. */
  label: string
}

export function SuggestionPin({ marker, onClick, onHoverChange, label }: SuggestionPinProps) {
  const glyph = STATUS_GLYPH[marker.status]
  const ring = marker.familyColor ?? 'var(--color-text-muted)'

  return (
    <button
      type="button"
      className={suggestionPinClassName(marker)}
      style={{ background: ring }}
      onClick={() => onClick?.(marker.id)}
      onMouseEnter={() => onHoverChange?.(true)}
      onMouseLeave={() => onHoverChange?.(false)}
      title={label}
      aria-label={`${label} — ${marker.category}, ${marker.status}`}
      data-testid="suggestion-pin"
      data-category={marker.category}
      data-status={marker.status}
    >
      <svg
        className="k-pin__icon"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.4}
        aria-hidden="true"
        dangerouslySetInnerHTML={{ __html: CATEGORY_ICON_PATHS[marker.category] }}
      />
      {glyph ? (
        <span className="k-pin__status-glyph" aria-hidden="true">
          {glyph}
        </span>
      ) : null}
    </button>
  )
}
