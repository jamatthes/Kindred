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

/** `types` rides along on the prediction Google already returns — no second request, no extra
 *  billing — which is what makes the create form's type guess free (`design.md` > "Type
 *  inference from Places"). Empty when Google sends none. */
export type PlacePrediction = { placeId: string; description: string; types: string[] }

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
  /** Google's place categories, used only to guess our own `type` — never persisted. */
  types: string[]
  /** The place's own website, when Google has one. Live-fetched on card open like everything
   *  else here and **never persisted** — which is precisely why the create form stops asking
   *  the user for a link once a `place_id` is set: the answer is already available, for free,
   *  every time the card opens. */
  website: string | null
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
              results: { place_id: string; description: string; types?: string[] }[] | null,
              status: string,
            ) => void,
          ): void
        }
        PlacesService: new (attrNode: HTMLDivElement) => {
          getDetails(
            request: { placeId: string; fields: string[] },
            callback: (result: GooglePlaceResult | null, status: string) => void,
          ): void
          findPlaceFromQuery(
            request: { query: string; fields: string[] },
            callback: (results: GooglePlaceResult[] | null, status: string) => void,
          ): void
        }
        PlacesServiceStatus: { OK: string }
      }
    }
  }
}

type GooglePlaceResult = {
  place_id?: string
  name?: string
  formatted_address?: string
  geometry?: { location?: { lat(): number; lng(): number } }
  photos?: { getUrl(opts: { maxWidth: number }): string }[]
  rating?: number
  opening_hours?: { weekday_text?: string[] }
  types?: string[]
  website?: string
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
      resolve(
        results.map((r) => ({ placeId: r.place_id, description: r.description, types: r.types ?? [] })),
      )
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
        // `types` is a Basic-tier field like `name`/`geometry`, so asking for it costs
        // nothing beyond the Details call this flow already makes.
        // `website` is a Contact-tier field, but `opening_hours` on the line above already
        // puts this call in that tier — so asking for it costs nothing extra, and it is what
        // lets the create form stop asking the user for a listing link.
        fields: [
          'name',
          'formatted_address',
          'geometry',
          'photos',
          'rating',
          'opening_hours',
          'types',
          'website',
        ],
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
    types: result.types ?? [],
    website: result.website ?? null,
  }

  detailsCache.set(placeId, { expiresAt: Date.now() + CACHE_TTL_MS, details })
  return details
}

/**
 * Finds the place a piece of free text refers to — the name off a pasted link, typically.
 *
 * This is what makes "paste a shop's website and get its location" work: a URL is not
 * something Google can look up, but the page's own title ("The Games Shop Aldershot") is
 * exactly what its Places index is built on. `findPlaceFromQuery` is the single-answer
 * search — it either recognises the text or it does not, which suits a best-effort fill:
 * `null` simply means the user still places the pin themselves.
 *
 * Basic-tier fields only (`place_id`, `name`, `geometry`, `formatted_address`, `types`), so
 * this is the cheapest Places call available; it runs once per pasted link, never on render.
 */
export async function findPlaceFromText(query: string): Promise<PlaceLocation | null> {
  const trimmed = query.trim()
  if (!trimmed) return null
  const places = googleGlobal().google?.maps?.places
  if (!places) return null

  const service = getPlacesService()
  return new Promise((resolve) => {
    service.findPlaceFromQuery(
      { query: trimmed, fields: ['place_id', 'name', 'formatted_address', 'geometry', 'types'] },
      (results, status) => {
        const first = results?.[0]
        if (status !== places.PlacesServiceStatus.OK || !first?.geometry?.location) {
          resolve(null)
          return
        }
        resolve({
          placeId: first.place_id ?? '',
          name: first.name ?? trimmed,
          address: first.formatted_address ?? '',
          lat: first.geometry.location.lat(),
          lng: first.geometry.location.lng(),
          types: first.types ?? [],
        })
      },
    )
  })
}

/** What a text lookup can answer: where the place is and roughly what it is. A subset of
 *  `PlaceDetails` — no photos, hours or rating, because none were asked for. */
export type PlaceLocation = {
  placeId: string
  name: string
  address: string
  lat: number
  lng: number
  types: string[]
}

/** Test/dev-only: empties the TTL cache so a test's mocked SDK is exercised deterministically. */
export function clearPlaceDetailsCache(): void {
  detailsCache.clear()
}
