/**
 * A Google place, shown the way Google shows it — in the shell's right-hand panel.
 *
 * Kindred is an overlay on Google's map, not a replacement for it: when someone clicks a
 * place, the facts they expect are the ones Google Maps would give them (photos, rating,
 * category, address, hours, website, phone). Making them leave for that, or re-typing a
 * subset into a suggestion first, would be the app hiding data it already has in hand.
 *
 * **Nothing here is persisted.** Everything is fetched live by `placesClient` when the panel
 * opens and discarded when it closes — the HARD INVARIANT in `design.md`. The one thing this
 * panel writes is the user's decision: "Add as suggestion" hands the place to the create
 * form, which sends `place_id` plus what the user typed, and nothing else.
 *
 * The panel is deliberately *read-only until asked*: a place on the map is not yet part of
 * the trip, and looking at one should not commit anybody to anything.
 */

import { Button, Spinner } from '../../app/ui/primitives'
import type { PlaceDetails } from './placesClient'
import type { PlaceSeed } from './CreateSuggestionForm'
import { inferSuggestionType } from './placeType'
import './placeProfilePanel.css'

const TYPE_LABEL: Record<string, string> = {
  accommodation: 'Somewhere to stay',
  meal: 'Somewhere to eat',
  activity: 'Something to do',
  region: 'An area',
  other: 'A place',
}

export type PlaceProfilePanelProps = {
  place: PlaceDetails | null
  loading: boolean
  error: string | null
  canAdd: boolean
  onAdd: (seed: PlaceSeed) => void
  onClose: () => void
}

export function PlaceProfilePanel({ place, loading, error, canAdd, onAdd, onClose }: PlaceProfilePanelProps) {
  if (loading) {
    return (
      <div className="place-profile" aria-busy="true">
        <div className="place-profile__loading">
          <Spinner />
        </div>
      </div>
    )
  }

  if (error || !place) {
    return (
      <div className="place-profile">
        <div className="place-profile__head">
          <h2>Place</h2>
          <button type="button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="place-profile__muted">{error ?? 'Nothing to show for this place.'}</p>
      </div>
    )
  }

  const category = TYPE_LABEL[inferSuggestionType(place.types)]
  const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${place.lat},${place.lng}&query_place_id=${encodeURIComponent(place.placeId)}`

  return (
    <div className="place-profile">
      <div className="place-profile__head">
        <h2>{place.name}</h2>
        <button type="button" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>

      {place.photoUrls.length > 0 ? (
        <div className="place-profile__photos">
          {place.photoUrls.slice(0, 6).map((url) => (
            <img key={url} src={url} alt="" loading="lazy" />
          ))}
        </div>
      ) : null}

      <div className="place-profile__meta">
        {place.rating !== null ? (
          <span className="place-profile__rating">
            {/* The count is not decoration: an average of four ratings and an average of
                forty thousand are different claims, and Google shows both for that reason. */}
            {place.rating.toFixed(1)}
            <span aria-hidden="true"> ★</span>
            {place.ratingCount !== null ? (
              <span className="place-profile__muted"> ({place.ratingCount.toLocaleString()})</span>
            ) : null}
          </span>
        ) : null}
        <span className="place-profile__muted">{category}</span>
        {place.openNow !== null ? (
          <span className={place.openNow ? 'place-profile__open' : 'place-profile__shut'}>
            {place.openNow ? 'Open now' : 'Closed'}
          </span>
        ) : null}
      </div>

      {place.editorialSummary ? <p className="place-profile__summary">{place.editorialSummary}</p> : null}

      {/* The primary action, above the reference detail: this panel exists to turn a place
          into a suggestion, and everything below it is what you read to decide. */}
      <div className="place-profile__actions">
        <Button
          disabled={!canAdd}
          onClick={() =>
            onAdd({
              placeId: place.placeId,
              name: place.name,
              address: place.address,
              position: { lat: place.lat, lng: place.lng },
              types: place.types,
            })
          }
        >
          Add as suggestion
        </Button>
        <a href={mapsUrl} target="_blank" rel="noreferrer" className="place-profile__link">
          Open in Google Maps
        </a>
      </div>

      <dl className="place-profile__facts">
        {place.address ? (
          <>
            <dt>Address</dt>
            <dd>{place.address}</dd>
          </>
        ) : null}
        {place.phone ? (
          <>
            <dt>Phone</dt>
            {/* A tel: link is the whole point of a number on a phone-shaped device. */}
            <dd>
              <a className="place-profile__link" href={`tel:${place.phone.replace(/\s+/g, '')}`}>
                {place.phone}
              </a>
            </dd>
          </>
        ) : null}
        {place.website ? (
          <>
            <dt>Website</dt>
            <dd>
              <a className="place-profile__link" href={place.website} target="_blank" rel="noreferrer">
                {hostOf(place.website)}
              </a>
            </dd>
          </>
        ) : null}
        {place.openingHoursText?.length ? (
          <>
            <dt>Opening hours</dt>
            <dd>
              <ul className="place-profile__hours">
                {place.openingHoursText.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
      </dl>

      {/* Required wherever Google's data is shown outside their own map. */}
      <p className="place-profile__attribution">Place information from Google</p>
    </div>
  )
}

/** `https://www.spitalfields.co.uk/whatever` → `spitalfields.co.uk`. The full URL in a narrow
 *  panel wraps into three lines of query string nobody reads. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}
