/**
 * Our card for one of Google's own base-map places (requirements S3b).
 *
 * Google renders an info window for these clicks with no way to add an action to it, so the
 * provider suppresses that window (`GoogleMapProvider`'s `click` handler calls `e.stop()`)
 * and this card takes its place — same facts, plus the one button the built-in window could
 * never carry.
 *
 * Nothing here is persisted. The details are fetched in the browser on card-open and
 * discarded when it closes; only `place_id` plus whatever the user keeps in the create form
 * is ever sent to the server (the HARD INVARIANT in `design.md`).
 */

import { Button, Spinner } from '../../app/ui/primitives'
import type { PlaceSeed } from './CreateSuggestionForm'
import './placePreviewCard.css'

export type PlacePreviewCardProps = {
  /** `null` while Place Details is still resolving. */
  place: PlaceSeed | null
  loading: boolean
  error: string | null
  canAdd: boolean
  /** Whether this card carries the actions. False on desktop, where the shell's side panel
   *  shows the full Google profile and owns "Add as suggestion" — the card is then just the
   *  map's answer to "which place did I click", and a second identical button next to the
   *  first is not a shortcut, it is a duplicate. True on mobile, where there is no side panel
   *  and this card is the only surface the place has. */
  showActions?: boolean
  /** Pinned over its place on the map (the normal case) rather than parked in a corner —
   *  draws the tail that points back down at the location. Off while the map cannot project
   *  a point yet, when a tail would point at nothing in particular. */
  anchored?: boolean
  onAdd: (place: PlaceSeed) => void
  onClose: () => void
}

export function PlacePreviewCard({
  place,
  loading,
  error,
  canAdd,
  anchored = false,
  showActions = true,
  onAdd,
  onClose,
}: PlacePreviewCardProps) {
  return (
    <div
      className={`place-preview${anchored ? ' place-preview--anchored' : ''}`}
      role="dialog"
      aria-label={place?.name ?? 'Place'}
    >
      <button type="button" className="place-preview__close" onClick={onClose} aria-label="Close">
        ×
      </button>

      {loading ? (
        <div className="place-preview__loading">
          <Spinner />
        </div>
      ) : error ? (
        <p className="place-preview__error">{error}</p>
      ) : place ? (
        <>
          <h3 className="place-preview__title">{place.name}</h3>
          {place.address ? <p className="place-preview__address">{place.address}</p> : null}
          {showActions ? (
          <div className="place-preview__actions">
            <Button onClick={() => onAdd(place)} disabled={!canAdd}>
              Add as suggestion
            </Button>
            {/* A plain Maps URL, not an API call — no key, no quota, ToS-fine (`design.md`). */}
            <a
              className="place-preview__link"
              href={`https://www.google.com/maps/search/?api=1&query=${place.position.lat},${place.position.lng}&query_place_id=${encodeURIComponent(place.placeId)}`}
              target="_blank"
              rel="noreferrer"
            >
              Open in Google Maps
            </a>
          </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
