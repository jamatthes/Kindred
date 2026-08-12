/**
 * Google Places, called from the browser only — the HARD INVARIANT in `design.md`.
 *
 * The server never proxies Place Details; this module is the entire client-side boundary.
 * Details fetched here are held in an in-memory cache with a short TTL (target 5 minutes,
 * cleared on reload — a plain module-level `Map` achieves both for free) purely to avoid
 * re-billing a rapid reopen, and are **never** sent to `suggestionsApi` — callers pass only
 * `place_id` plus whatever the user typed/kept in the form to the server.
 *
 * Feature-detected rather than assumed: no browser API key is configured yet
 * (`GoogleMapProvider`'s docblock says the same), so `placesAvailable()` lets the UI fall
 * back to "drop a pin instead" per `design.md`'s edge-case table rather than throwing.
 */

export type PlacePrediction = { placeId: string; description: string }

export type PlaceDetails = {
  placeId: string
  name: string
  address: string
  lat: number
  lng: number
  /** Live-fetched, never persisted — tier 1 of the photo-source ladder in `design.md`. */
  photoUrls: string[]
  rating: number | null
  openingHoursText: string[] | null
}

const CACHE_TTL_MS = 5 * 60 * 1000
const detailsCache = new Map<string, { expiresAt: number; details: PlaceDetails }>()

type GoogleGlobal = typeof window & {
  google?: {
    maps?: {
      places?: {
        AutocompleteService: new () => {
          getPlacePredictions(
            request: { input: string },
            callback: (
              results: { place_id: string; description: string }[] | null,
              status: string,
            ) => void,
          ): void
        }
        PlacesService: new (attrNode: HTMLDivElement) => {
          getDetails(
            request: { placeId: string; fields: string[] },
            callback: (result: GooglePlaceResult | null, status: string) => void,
          ): void
        }
        PlacesServiceStatus: { OK: string }
      }
    }
  }
}

type GooglePlaceResult = {
  name?: string
  formatted_address?: string
  geometry?: { location?: { lat(): number; lng(): number } }
  photos?: { getUrl(opts: { maxWidth: number }): string }[]
  rating?: number
  opening_hours?: { weekday_text?: string[] }
}

function googleGlobal(): GoogleGlobal {
  return window as GoogleGlobal
}

/** Whether the Maps JS SDK with the Places library has loaded. Checked fresh on every call
 * rather than cached, so a key added after page load (or the SDK finishing an async load)
 * is picked up without a reload. */
export function placesAvailable(): boolean {
  return typeof window !== 'undefined' && Boolean(googleGlobal().google?.maps?.places)
}

let sharedServiceNode: HTMLDivElement | null = null

function getPlacesService() {
  const places = googleGlobal().google?.maps?.places
  if (!places) throw new Error('Google Places is not available — check placesAvailable() first.')
  // `PlacesService` requires a `Map` or a plain DOM node; a detached node avoids depending
  // on a live `MapProvider` instance for what is a stateless lookup.
  if (!sharedServiceNode) sharedServiceNode = document.createElement('div')
  return new places.PlacesService(sharedServiceNode)
}

export async function autocompletePlaces(input: string): Promise<PlacePrediction[]> {
  if (!input.trim()) return []
  const places = googleGlobal().google?.maps?.places
  if (!places) return []
  const service = new places.AutocompleteService()
  return new Promise((resolve) => {
    service.getPlacePredictions({ input }, (results, status) => {
      if (status !== places.PlacesServiceStatus.OK || !results) {
        resolve([])
        return
      }
      resolve(results.map((r) => ({ placeId: r.place_id, description: r.description })))
    })
  })
}

/** Fetches Place Details for `placeId`, in the browser, and caches the result briefly.
 * Requests only the fields the UI actually renders — `design.md` forbids storing any of
 * this server-side, but the browser call itself should still ask for no more than it uses. */
export async function getPlaceDetails(placeId: string): Promise<PlaceDetails> {
  const cached = detailsCache.get(placeId)
  if (cached && cached.expiresAt > Date.now()) return cached.details

  const places = googleGlobal().google?.maps?.places
  if (!places) throw new Error('Google Places is not available — check placesAvailable() first.')

  const service = getPlacesService()
  const result = await new Promise<GooglePlaceResult>((resolve, reject) => {
    service.getDetails(
      {
        placeId,
        fields: ['name', 'formatted_address', 'geometry', 'photos', 'rating', 'opening_hours'],
      },
      (result, status) => {
        if (status !== places.PlacesServiceStatus.OK || !result) {
          reject(new Error(`Place Details failed: ${status}`))
          return
        }
        resolve(result)
      },
    )
  })

  const details: PlaceDetails = {
    placeId,
    name: result.name ?? '',
    address: result.formatted_address ?? '',
    lat: result.geometry?.location?.lat() ?? 0,
    lng: result.geometry?.location?.lng() ?? 0,
    photoUrls: (result.photos ?? []).slice(0, 8).map((p) => p.getUrl({ maxWidth: 640 })),
    rating: result.rating ?? null,
    openingHoursText: result.opening_hours?.weekday_text ?? null,
  }

  detailsCache.set(placeId, { expiresAt: Date.now() + CACHE_TTL_MS, details })
  return details
}

/** Test/dev-only: empties the TTL cache so a test's mocked SDK is exercised deterministically. */
export function clearPlaceDetailsCache(): void {
  detailsCache.clear()
}
