/**
 * The one create form, seeded by the four entry points in `design.md` > "Creation flows":
 * search, drop-pin, draw-region, paste-URL. All four converge here; only what is in the
 * form at save time is ever sent (S3: Google-returned details are never persisted, only
 * `place_id` plus what the user kept/typed).
 *
 * Map interaction (the click that drops a pin or adds a region vertex) is owned by
 * `MapSuggestionsScreen`, which is the only thing holding a live `MapCanvas` — this
 * component consumes clicks it is handed via `pendingClick`/`onConsumeClick` rather than
 * reaching for the map itself, the same separation `MapCanvas` enforces between the
 * imperative provider and everything declarative around it.
 *
 * **Deviations from `design.md`, recorded here per the docs-first rule** (also noted in
 * `plan/features/map-suggestions/design.md`):
 * - The provisional pin is repositioned by clicking again, not dragged — `MapProvider`
 *   (`features/map/MapProvider.ts`) exposes no marker-drag primitive, only `markerClick`/
 *   `markerHover`/`polygonClick`/`mapClick`. Adding one is a provider-layer change out of
 *   this phase's scope; click-to-reposition is the same outcome through the events that
 *   exist today.
 * - The polygon region tool is click-to-place-vertex plus "Finish shape", not freehand
 *   drag — `design.md` itself names click-to-place as one of the two sanctioned draw modes
 *   ("the draw tool defaults to freehand/click-to-place polygon outlining"), so this is
 *   already within spec, not a reduction of it.
 * - The circle tool sets its radius from two clicks (centre, then edge) for the same reason.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useValidatedField } from '../../app/ui/useValidatedField'
import { ApiError } from '../../app/apiClient'
import { suggestionsApi } from './api'
import { autocompletePlaces, findPlaceFromText, getPlaceDetails, placesAvailable } from './placesClient'
import type { PlacePrediction } from './placesClient'
import { inferSuggestionType } from './placeType'
import { circleGeometry, haversineM, polygonGeometry, regionCentroid } from './geometry'
import type { LatLng } from '../map/types'
import type { LinkPreview, Suggestion, SuggestionCreateInput, SuggestionType } from '../../app/types'
import './CreateSuggestionForm.css'

export type CreateMode = 'search' | 'drop-pin' | 'draw-region' | 'url'

const TYPE_LABEL: Record<SuggestionType, string> = {
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
  other: 'Other',
  region: 'Region',
}

export type CreateSuggestionFormProps = {
  onClose: () => void
  onCreated: (suggestion: Suggestion) => void
  /** The most recent unclaimed map click while this form is open. `null` once consumed. */
  pendingClick: LatLng | null
  onConsumeClick: () => void
  existingSuggestions: Suggestion[]
  onFocusExisting: (id: string) => void
  /** Which entry point opened the form — `MapSuggestionsScreen`'s "Suggest a place" button
   * (search), the map toolbar's drop-pin/draw-region buttons, or the empty-state list's
   * drop-pin shortcut. Defaults to `'search'` so every existing caller that does not pass
   * this keeps its current behaviour. **Found by the M3 integration pass's own Playwright
   * smoke**: the parent already tracked a `createMode` state for its toolbar hint text and
   * `onMapClick` gating, but never passed it in here, so every entry point silently opened
   * on the search tab regardless of which button was clicked. */
  initialMode?: CreateMode
  /** Fired whenever the user switches tabs inside the form, so the parent's own gating
   * (`MapSuggestionsScreen`'s `onMapClick`, which only forwards a click when its own
   * `createMode` state says `'drop-pin'`/`'draw-region'`) tracks the tab that is actually
   * showing rather than only the one the form opened on. **Found by the same Playwright
   * smoke as `initialMode`, one layer deeper**: passing `initialMode` fixed the entry-point
   * case, but a user opening in search mode and then clicking the "Drop a pin" tab by hand
   * — the ordinary way to reach it from the toolbar's default button — still could not
   * click the map, because the parent never learned the tab had changed. */
  onModeChange?: (mode: CreateMode) => void
  /** A place the user picked *outside* this form — today, a click on one of the base map's
   * own Google POIs (`design.md` S3b). The parent has already paid for the Place Details
   * call to render its card, so the form takes the result rather than fetching it a second
   * time. Seeds exactly what picking a search prediction seeds, guessed type included. */
  seedPlace?: PlaceSeed | null
}

/** What the parent knows about a place it has already looked up. Mirrors the fields
 *  `pickPrediction` sets, so the two entry points cannot drift apart. */
export type PlaceSeed = {
  placeId: string
  name: string
  address: string
  position: LatLng
  /** Google's raw categories — only ever used to guess our type; never persisted. */
  types: string[]
}

/** The distinctive part of a URL's host, as a search query: `https://www.example.co.uk/x`
 *  → `example`. Strips `www.` and the public suffix, which carry no meaning for a lookup. */
function domainAsQuery(url: string): string {
  try {
    const host = new URL(url.trim()).hostname.replace(/^www\./, '')
    return host.split('.')[0] ?? ''
  } catch {
    // Not a URL yet — the user is still typing. Nothing to search for.
    return ''
  }
}

function validateTitle(value: string): string | null {
  return value.trim().length === 0 ? 'Give this a title.' : null
}

export function CreateSuggestionForm({
  onClose,
  onCreated,
  pendingClick,
  onConsumeClick,
  existingSuggestions,
  onFocusExisting,
  initialMode = 'search',
  onModeChange,
  seedPlace = null,
}: CreateSuggestionFormProps) {
  // Fixed for the life of the form. The mode is chosen by the entry point — a POI click, a
  // right-click, the toolbar's "Paste a link" — and there is no longer any in-form control
  // that changes it, so this is state only in the sense that it was passed in once.
  const [mode] = useState<CreateMode>(initialMode)
  const [type, setType] = useState<SuggestionType>('accommodation')
  const title = useValidatedField(validateTitle)
  const [notes, setNotes] = useState('')
  const [externalUrl, setExternalUrl] = useState('')
  const [coords, setCoords] = useState<LatLng | null>(null)
  const [placeId, setPlaceId] = useState<string | null>(null)
  const [placeSnapshot, setPlaceSnapshot] = useState<{ name: string; address: string } | null>(null)

  const [searchInput, setSearchInput] = useState('')
  const [predictions, setPredictions] = useState<PlacePrediction[]>([])
  const [searchError, setSearchError] = useState<string | null>(null)

  const [drawShape, setDrawShape] = useState<'circle' | 'polygon'>('polygon')
  const [polygonPoints, setPolygonPoints] = useState<LatLng[]>([])
  const [circleCenter, setCircleCenter] = useState<LatLng | null>(null)
  const [circleRadiusM, setCircleRadiusM] = useState<number | null>(null)

  const [linkStatus, setLinkStatus] = useState<'idle' | 'checking' | 'checked'>('idle')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (mode === 'draw-region') setType('region')
  }, [mode])

  // Tells the parent which tab is showing now, not just which one the form opened on —
  // see `onModeChange`'s own doc comment for why this is load-bearing, not a courtesy.
  useEffect(() => {
    onModeChange?.(mode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  // Seeded from outside (POI click). Keyed on `placeId` so re-renders don't clobber edits
  // the user has since made — only a genuinely different place re-seeds the form.
  const seededPlaceIdRef = useRef<string | null>(null)
  const seededPlaceNameRef = useRef<string | null>(null)
  useEffect(() => {
    if (!seedPlace || seededPlaceIdRef.current === seedPlace.placeId) return
    // Re-seeding an open form (the user clicked a different place on the map) must not throw
    // away a title they typed themselves. Overwrite only what the form itself filled in: an
    // empty title, or the previous place's name still sitting there untouched.
    const previousName = seededPlaceNameRef.current
    if (!title.value.trim() || title.value === previousName) {
      title.setValue(seedPlace.name)
    }
    seededPlaceIdRef.current = seedPlace.placeId
    seededPlaceNameRef.current = seedPlace.name
    setCoords(seedPlace.position)
    setPlaceId(seedPlace.placeId)
    setPlaceSnapshot({ name: seedPlace.name, address: seedPlace.address })
    setType(inferSuggestionType(seedPlace.types))
    setSearchInput(seedPlace.name)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedPlace])

  // --- Search -------------------------------------------------------------------------
  useEffect(() => {
    // A resolved place hides the search box, so nothing here should still be searching for
    // it. Without this guard the seeded name went straight back into autocomplete and the
    // form showed a list of alternatives underneath the place the user had just chosen —
    // including, absurdly, the place itself.
    if (mode !== 'search' || placeId || !searchInput.trim()) {
      setPredictions([])
      return
    }
    if (!placesAvailable()) {
      setSearchError('Place search is unavailable right now — try dropping a pin instead.')
      return
    }
    setSearchError(null)
    const timer = setTimeout(() => {
      void autocompletePlaces(searchInput).then(setPredictions)
    }, 250)
    return () => clearTimeout(timer)
  }, [mode, placeId, searchInput])

  async function pickPrediction(prediction: PlacePrediction) {
    try {
      const details = await getPlaceDetails(prediction.placeId)
      title.setValue(details.name || prediction.description)
      setCoords({ lat: details.lat, lng: details.lng })
      setPlaceId(details.placeId)
      setPlaceSnapshot({ name: details.name, address: details.address })
      // Preselect, never impose: the dropdown below stays editable, and `region` is left
      // alone because the draw-region tab owns that type outright.
      if (mode !== 'draw-region') {
        setType(inferSuggestionType(details.types.length ? details.types : prediction.types))
      }
      setPredictions([])
      setSearchInput(details.name)
    } catch {
      setSearchError('That place could not be loaded — try again or drop a pin instead.')
    }
  }

  // --- Drop pin -------------------------------------------------------------------------
  useEffect(() => {
    if (mode !== 'drop-pin' || !pendingClick) return
    setCoords(pendingClick)
    setPlaceId(null)
    setPlaceSnapshot(null)
    onConsumeClick()
  }, [mode, pendingClick, onConsumeClick])

  // --- Draw region ------------------------------------------------------------------------
  useEffect(() => {
    if (mode !== 'draw-region' || !pendingClick) return
    if (drawShape === 'polygon') {
      setPolygonPoints((current) => [...current, pendingClick])
    } else if (!circleCenter) {
      setCircleCenter(pendingClick)
    } else {
      setCircleRadiusM(haversineM(circleCenter, pendingClick))
    }
    onConsumeClick()
  }, [mode, pendingClick, drawShape, circleCenter, onConsumeClick])

  const regionGeometry = useMemo(() => {
    if (drawShape === 'circle' && circleCenter && circleRadiusM) {
      return circleGeometry(circleCenter, circleRadiusM)
    }
    if (drawShape === 'polygon' && polygonPoints.length >= 3) {
      return polygonGeometry(polygonPoints)
    }
    return null
  }, [drawShape, circleCenter, circleRadiusM, polygonPoints])

  const regionCentroidPoint = regionGeometry ? regionCentroid(regionGeometry) : null

  function resetShape() {
    setPolygonPoints([])
    setCircleCenter(null)
    setCircleRadiusM(null)
  }

  // --- Paste URL ------------------------------------------------------------------------
  useEffect(() => {
    if (mode !== 'url' || !externalUrl.trim()) return
    const timer = setTimeout(() => {
      setLinkStatus('checking')
      suggestionsApi
        .linkPreview(externalUrl.trim())
        .then(async (preview: LinkPreview | undefined) => {
          setLinkStatus('checked')
          if (preview) {
            if (!title.value.trim() && preview.title) title.setValue(preview.title)
            const extraNotes = [preview.facts, preview.locality].filter(Boolean).join(' · ')
            if (extraNotes && !notes) setNotes(extraNotes)
            if (preview.lat !== undefined && preview.lng !== undefined && !coords) {
              setCoords({ lat: preview.lat, lng: preview.lng })
              return
            }
          }
          // The link named a place but not a location — the ordinary case for a shop's own
          // website, which has no geo metadata at all. Google cannot look up a URL, but the
          // page's title ("The Games Shop Aldershot") is exactly what its Places index is
          // built on, so we search for that. A site with no title falls back to its domain
          // ("thegamesshopaldershot.co.uk" → "thegamesshopaldershot"), which is a
          // surprisingly good query for a small business.
          if (coords || !placesAvailable()) return
          const query = preview?.title?.trim() || domainAsQuery(externalUrl)
          const found = query ? await findPlaceFromText([query, preview?.locality].filter(Boolean).join(' ')) : null
          if (!found) return
          setCoords({ lat: found.lat, lng: found.lng })
          if (found.placeId) setPlaceId(found.placeId)
          setPlaceSnapshot({ name: found.name, address: found.address })
          if (!title.value.trim()) title.setValue(found.name)
          setType(inferSuggestionType(found.types))
        })
        .catch(() => setLinkStatus('checked')) // best-effort — a failure is silent, per design.md
    }, 500)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, externalUrl])

  // --- Duplicate warning ------------------------------------------------------------------
  const duplicate =
    placeId && type === 'accommodation'
      ? existingSuggestions.find((s) => s.place_id === placeId && s.type === 'accommodation')
      : undefined

  async function handleSubmit() {
    if (!title.validate()) return
    const location = mode === 'draw-region' ? regionCentroidPoint : coords
    if (!location) {
      setSubmitError(
        mode === 'draw-region' ? 'Finish the shape before saving.' : 'Set a location before saving.',
      )
      return
    }
    if (mode === 'draw-region' && !regionGeometry) {
      setSubmitError('Finish the shape before saving.')
      return
    }

    // `trip_id` is deliberately never sent — see the field's own comment on
    // `SuggestionCreateInput` (app/types.ts): the real `POST /suggestions` derives the trip
    // from the session's single active trip and rejects an extra field.
    const body: SuggestionCreateInput = {
      type,
      title: title.value.trim(),
      notes: notes.trim() || undefined,
      lat: location.lat,
      lng: location.lng,
      geometry_geojson: regionGeometry ?? undefined,
      place_id: placeId ?? undefined,
      place_snapshot: placeSnapshot ?? undefined,
      external_url: externalUrl.trim() || undefined,
      // A region the user *searched for* rather than drew: ask the server for the real OSM
      // boundary instead of shipping a point and letting it render as a bare pin. Google's
      // own boundary polygons are render-only and licensed, so the search result cannot
      // carry the shape — the place's name is the whole input the lookup needs.
      boundary_query:
        type === 'region' && !regionGeometry
          ? (placeSnapshot?.name || title.value).trim() || undefined
          : undefined,
    }

    setSubmitting(true)
    setSubmitError(null)
    try {
      const created = await suggestionsApi.create(body)
      onCreated(created)
      onClose()
    } catch (cause) {
      // The one failure worth naming: OpenStreetMap has no boundary for that name. Telling
      // the user to draw it is actionable; "that could not be saved" sends them round the
      // same loop.
      setSubmitError(
        cause instanceof ApiError && cause.code === 'boundary_not_found'
          ? cause.message
          : 'That could not be saved. Try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="sugg-create" role="dialog" aria-modal="true" aria-label="Suggest a place">
      <div className="sugg-create__head">
        <h2>Suggest a place</h2>
        <button type="button" className="sugg-create__close" onClick={onClose} aria-label="Close">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>


      {mode !== 'draw-region' ? (
        <label className="k-field">
          <span className="k-field__label">What is this?</span>
          <select className="k-field__input" value={type} onChange={(e) => setType(e.target.value as SuggestionType)}>
            {/* `region` belongs here on the search tab: searching "Yorkshire" is the
                named-locality case, and the server turns it into a real OSM boundary on save
                (`design.md` > "Named-locality regions"). Leaving it out was why a searched
                county could only ever be filed as an activity — and why the type guess had
                nowhere to put its answer. A dropped pin still cannot be a region: there is no
                name to look a boundary up by, only a point. */}
            {((mode === 'search'
              ? ['accommodation', 'activity', 'meal', 'other', 'region']
              : ['accommodation', 'activity', 'meal', 'other']) as SuggestionType[]).map(
              (t) => (
                <option key={t} value={t}>
                  {TYPE_LABEL[t]}
                </option>
              ),
            )}
          </select>
          {mode === 'search' && type === 'region' ? (
            <p className="sugg-create__hint">
              The outline comes from OpenStreetMap when you save. If there is none, draw the area instead.
            </p>
          ) : null}
        </label>
      ) : null}

      {mode === 'search' ? (
        <div className="sugg-create__search">
          {/* Nothing at all once a place is resolved. The name is already in the Title field
              below — repeating it here as a second, differently-styled copy made the same
              string look like two competing facts — and the address rides under that field
              where it reads as the title's subtitle. Before a place is picked, this is the
              search box. */}
          {placeId && placeSnapshot ? null : (
            <TextField
              label="Search for a place"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Hotel, restaurant, attraction…"
            />
          )}
          {searchError ? <Banner tone="info">{searchError}</Banner> : null}
          {predictions.length > 0 ? (
            <ul className="sugg-create__predictions">
              {predictions.map((p) => (
                <li key={p.placeId}>
                  <button type="button" onClick={() => void pickPrediction(p)}>
                    {p.description}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {mode === 'drop-pin' ? (
        <p className="sugg-create__hint" aria-live="polite">
          {coords
            ? `Pin placed at ${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)} — click the map again to move it.`
            : 'Click anywhere on the map to drop the pin.'}
        </p>
      ) : null}

      {mode === 'draw-region' ? (
        <div className="sugg-create__draw">
          <div className="sugg-create__shape-toggle" role="group" aria-label="Shape">
            <button
              type="button"
              aria-pressed={drawShape === 'polygon'}
              className={drawShape === 'polygon' ? 'is-on' : ''}
              onClick={() => {
                setDrawShape('polygon')
                resetShape()
              }}
            >
              Polygon
            </button>
            <button
              type="button"
              aria-pressed={drawShape === 'circle'}
              className={drawShape === 'circle' ? 'is-on' : ''}
              onClick={() => {
                setDrawShape('circle')
                resetShape()
              }}
            >
              Quick circle
            </button>
          </div>
          <p className="sugg-create__hint" aria-live="polite">
            {drawShape === 'polygon'
              ? `Click the map to add points (${polygonPoints.length} so far, need at least 3).`
              : !circleCenter
                ? 'Click the map to set the centre.'
                : `Click again to set the radius (${circleRadiusM ? `${Math.round(circleRadiusM)} m` : 'not set'}).`}
          </p>
          {(polygonPoints.length > 0 || circleCenter) ? (
            <Button variant="secondary" type="button" onClick={resetShape}>
              Start over
            </Button>
          ) : null}
          {regionCentroidPoint ? (
            <p className="sugg-create__hint">
              Centre point: {regionCentroidPoint.lat.toFixed(4)}, {regionCentroidPoint.lng.toFixed(4)}
            </p>
          ) : null}
        </div>
      ) : null}

      {mode === 'url' ? (
        <div className="sugg-create__url">
          <TextField
            label="Listing link"
            type="url"
            value={externalUrl}
            onChange={(e) => setExternalUrl(e.target.value)}
            placeholder="https://www.airbnb.co.uk/rooms/…"
          />
          {linkStatus === 'checking' ? <p className="sugg-create__hint">Looking for a preview…</p> : null}
          <p className="sugg-create__hint">
            There is no Airbnb API — this is a best-effort preview only. Drop a pin or search to set the
            location.
          </p>
        </div>
      ) : null}

      <TextField label="Title" {...title.inputProps} error={title.error} />
      {/* The address as the title's subtitle: one fact, directly under the name it belongs
          to, rather than a separate boxed panel restating both. */}
      {placeSnapshot?.address ? <p className="sugg-create__address">{placeSnapshot.address}</p> : null}
      <label className="k-field">
        <span className="k-field__label">Notes</span>
        <textarea className="k-field__input" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
      </label>
      {/* Not asked for once the suggestion carries a `place_id`: Google already knows this
          place's website, the detail card fetches it on open (for free — same Contact tier as
          the opening hours it already requests), and asking a user to paste a link the app
          can look up itself is work we are inventing for them. It stays for a dropped pin and
          for the paste-a-link flow, where there is no place to look anything up by — that is
          requirement S6 (an Airbnb listing has no Google place at all). */}
      {mode !== 'url' && !placeId ? (
        <TextField
          label="Listing link (optional)"
          type="url"
          value={externalUrl}
          onChange={(e) => setExternalUrl(e.target.value)}
        />
      ) : null}

      {duplicate ? (
        <Banner tone="info">
          Someone already suggested this place —{' '}
          <button type="button" className="sugg-create__link" onClick={() => onFocusExisting(duplicate.id)}>
            {duplicate.title}
          </button>
          . You can still save this one.
        </Banner>
      ) : null}

      {submitError ? <Banner tone="error">{submitError}</Banner> : null}

      <div className="sugg-create__actions">
        <Button variant="secondary" onClick={onClose} disabled={submitting}>
          Cancel
        </Button>
        <Button onClick={() => void handleSubmit()} busy={submitting}>
          Save suggestion
        </Button>
      </div>
    </div>
  )
}
