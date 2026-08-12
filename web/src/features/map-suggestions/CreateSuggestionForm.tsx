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

import { useEffect, useMemo, useState } from 'react'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useValidatedField } from '../../app/ui/useValidatedField'
import { suggestionsApi } from './api'
import { autocompletePlaces, getPlaceDetails, placesAvailable } from './placesClient'
import type { PlacePrediction } from './placesClient'
import { circleGeometry, haversineM, polygonGeometry, regionCentroid } from './geometry'
import type { LatLng } from '../map/types'
import type { LinkPreview, Suggestion, SuggestionCreateInput, SuggestionType } from '../../app/types'
import './CreateSuggestionForm.css'

export type CreateMode = 'search' | 'drop-pin' | 'draw-region' | 'url'

const MODE_LABEL: Record<CreateMode, string> = {
  search: 'Search a place',
  'drop-pin': 'Drop a pin',
  'draw-region': 'Draw a region',
  url: 'Paste a link',
}

const TYPE_LABEL: Record<SuggestionType, string> = {
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
  region: 'Region',
}

export type CreateSuggestionFormProps = {
  tripId: string
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
}

function validateTitle(value: string): string | null {
  return value.trim().length === 0 ? 'Give this a title.' : null
}

export function CreateSuggestionForm({
  tripId,
  onClose,
  onCreated,
  pendingClick,
  onConsumeClick,
  existingSuggestions,
  onFocusExisting,
  initialMode = 'search',
}: CreateSuggestionFormProps) {
  const [mode, setMode] = useState<CreateMode>(initialMode)
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

  // --- Search -------------------------------------------------------------------------
  useEffect(() => {
    if (mode !== 'search' || !searchInput.trim()) {
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
  }, [mode, searchInput])

  async function pickPrediction(prediction: PlacePrediction) {
    try {
      const details = await getPlaceDetails(prediction.placeId)
      title.setValue(details.name || prediction.description)
      setCoords({ lat: details.lat, lng: details.lng })
      setPlaceId(details.placeId)
      setPlaceSnapshot({ name: details.name, address: details.address })
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
        .then((preview: LinkPreview | undefined) => {
          setLinkStatus('checked')
          if (!preview) return // 204 — normal, silent
          if (!title.value.trim() && preview.title) title.setValue(preview.title)
          const extraNotes = [preview.facts, preview.locality].filter(Boolean).join(' · ')
          if (extraNotes && !notes) setNotes(extraNotes)
          if (preview.lat !== undefined && preview.lng !== undefined && !coords) {
            setCoords({ lat: preview.lat, lng: preview.lng })
          }
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

    const body: SuggestionCreateInput = {
      trip_id: tripId,
      type,
      title: title.value.trim(),
      notes: notes.trim() || undefined,
      lat: location.lat,
      lng: location.lng,
      geometry_geojson: regionGeometry ?? undefined,
      place_id: placeId ?? undefined,
      place_snapshot: placeSnapshot ?? undefined,
      external_url: externalUrl.trim() || undefined,
    }

    setSubmitting(true)
    setSubmitError(null)
    try {
      const created = await suggestionsApi.create(body)
      onCreated(created)
      onClose()
    } catch {
      setSubmitError('That could not be saved. Try again.')
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

      <div className="sugg-create__modes" role="tablist" aria-label="How to add this">
        {(Object.keys(MODE_LABEL) as CreateMode[]).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            className={`sugg-create__mode${mode === m ? ' is-on' : ''}`}
            onClick={() => setMode(m)}
          >
            {MODE_LABEL[m]}
          </button>
        ))}
      </div>

      {mode !== 'draw-region' ? (
        <label className="k-field">
          <span className="k-field__label">What is this?</span>
          <select className="k-field__input" value={type} onChange={(e) => setType(e.target.value as SuggestionType)}>
            {(['accommodation', 'activity', 'meal'] as SuggestionType[]).map((t) => (
              <option key={t} value={t}>
                {TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {mode === 'search' ? (
        <div className="sugg-create__search">
          <TextField
            label="Search for a place"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Hotel, restaurant, attraction…"
          />
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
          {coords ? (
            <p className="sugg-create__hint">Location set from Google Places — edit the details below.</p>
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
      <label className="k-field">
        <span className="k-field__label">Notes</span>
        <textarea className="k-field__input" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
      </label>
      {mode !== 'url' ? (
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
