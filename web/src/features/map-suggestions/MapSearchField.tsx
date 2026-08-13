/**
 * The map toolbar's place search — the map-first replacement for opening a form and *then*
 * searching inside it (`design.md` > "Map-first interaction model", 1).
 *
 * Picking a prediction resolves Place Details once, here, and hands the whole result up as a
 * `PlaceSeed`. The parent uses it twice — to fly the map there and to seed the create form —
 * without a second billed lookup, which is the same discipline the POI-click path follows.
 *
 * Degrades honestly: with no Places SDK (no browser key, or the script blocked) the field
 * disables itself and says so, rather than swallowing every keystroke into a search that can
 * never return. Dropping a pin still works in that state, which is the point.
 */

import { useEffect, useRef, useState } from 'react'
import { autocompletePlaces, getPlaceDetails, placesAvailable } from './placesClient'
import type { PlacePrediction } from './placesClient'
import type { PlaceSeed } from './CreateSuggestionForm'
import './mapSearchField.css'

const DEBOUNCE_MS = 250

export function MapSearchField({ onPick }: { onPick: (seed: PlaceSeed) => void }) {
  const [input, setInput] = useState('')
  const [predictions, setPredictions] = useState<PlacePrediction[]>([])
  const [error, setError] = useState<string | null>(null)
  const [available, setAvailable] = useState(true)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!input.trim()) {
      setPredictions([])
      return
    }
    if (!placesAvailable()) {
      setAvailable(false)
      return
    }
    setAvailable(true)
    setError(null)
    const timer = setTimeout(() => {
      void autocompletePlaces(input).then(setPredictions)
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [input])

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setPredictions([])
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [])

  async function pick(prediction: PlacePrediction) {
    try {
      const details = await getPlaceDetails(prediction.placeId)
      setPredictions([])
      setInput('')
      onPick({
        placeId: details.placeId,
        name: details.name || prediction.description,
        address: details.address,
        position: { lat: details.lat, lng: details.lng },
        // Details' own categories win when present; the prediction's are the fallback, which
        // is all we have if Details came back thin.
        types: details.types.length ? details.types : prediction.types,
      })
    } catch {
      setError('That place could not be loaded — try again or drop a pin instead.')
    }
  }

  return (
    <div className="map-search" ref={rootRef}>
      <input
        type="search"
        className="map-search__input"
        placeholder="Search for a place"
        aria-label="Search for a place"
        value={input}
        disabled={!available}
        onChange={(event) => setInput(event.target.value)}
      />
      {!available ? (
        <p className="map-search__note" role="status">
          Place search is unavailable — right-click the map to drop a pin instead.
        </p>
      ) : null}
      {error ? (
        <p className="map-search__note" role="status">
          {error}
        </p>
      ) : null}
      {predictions.length ? (
        <ul className="map-search__results">
          {predictions.map((prediction) => (
            <li key={prediction.placeId}>
              <button type="button" onClick={() => void pick(prediction)}>
                {prediction.description}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
