/**
 * `placesClient` — the browser-only boundary the HARD INVARIANT in `design.md` depends on.
 * Feature-detection (no key configured in this environment) and the short-TTL details cache
 * are the two behaviours worth pinning down without a live Google script.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('placesClient — feature detection', () => {
  afterEach(() => {
    // @ts-expect-error test-only cleanup of a global this module reads
    delete window.google
  })

  it('reports unavailable when window.google is absent, so the UI can fall back to drop-a-pin', async () => {
    const { placesAvailable } = await import('./placesClient')
    expect(placesAvailable()).toBe(false)
  })

  it('reports available once the Maps JS SDK (with the places library) has loaded', async () => {
    // @ts-expect-error minimal stand-in for the SDK global
    window.google = { maps: { places: {} } }
    const { placesAvailable } = await import('./placesClient')
    expect(placesAvailable()).toBe(true)
  })
})

describe('placesClient — getPlaceDetails caching', () => {
  const getDetails = vi.fn()

  beforeEach(async () => {
    getDetails.mockReset()
    getDetails.mockImplementation((_req, callback) => {
      callback(
        {
          name: 'Harbour House',
          formatted_address: '1 Harbour Rd',
          geometry: { location: { lat: () => 50.4, lng: () => -4.7 } },
          photos: [{ getUrl: () => 'https://example.com/photo.jpg' }],
          rating: 4.5,
        },
        'OK',
      )
    })
    // @ts-expect-error minimal stand-in for the SDK global
    window.google = {
      maps: {
        places: {
          PlacesService: class {
            getDetails = getDetails
          },
          PlacesServiceStatus: { OK: 'OK' },
        },
      },
    }
    const { clearPlaceDetailsCache } = await import('./placesClient')
    clearPlaceDetailsCache()
  })

  afterEach(() => {
    // @ts-expect-error test-only cleanup
    delete window.google
  })

  it('fetches details once and serves the second call from the in-memory cache', async () => {
    const { getPlaceDetails } = await import('./placesClient')
    const first = await getPlaceDetails('place-1')
    expect(first.name).toBe('Harbour House')
    expect(getDetails).toHaveBeenCalledTimes(1)

    const second = await getPlaceDetails('place-1')
    expect(second).toEqual(first)
    expect(getDetails).toHaveBeenCalledTimes(1) // cached — no re-fetch, no re-billing
  })
})
