/**
 * The create form — the HARD INVARIANT in `design.md` is tested directly here: whatever
 * Google Places returns in the browser, only `place_id` plus user-authored fields ever
 * reach `suggestionsApi.create`. Also covers the drop-pin and duplicate-warning flows.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Suggestion } from '../../app/types'

const create = vi.fn()
vi.mock('./api', () => ({
  suggestionsApi: { create: (...args: unknown[]) => create(...args), linkPreview: vi.fn() },
}))

const getPlaceDetails = vi.fn()
const autocompletePlaces = vi.fn()
vi.mock('./placesClient', () => ({
  placesAvailable: () => true,
  autocompletePlaces: (...args: unknown[]) => autocompletePlaces(...args),
  getPlaceDetails: (...args: unknown[]) => getPlaceDetails(...args),
}))

const { CreateSuggestionForm } = await import('./CreateSuggestionForm')

beforeEach(() => {
  create.mockReset()
  getPlaceDetails.mockReset()
  autocompletePlaces.mockReset()
})

function suggestion(overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 's1',
    type: 'accommodation',
    title: 'Existing place',
    notes: null,
    status: 'proposed',
    created_by: { user_id: 'u1', display_name: 'Alex', family_id: 'f1', family_color: 3 },
    lat: 50.4,
    lng: -4.7,
    geometry_geojson: null,
    place_id: 'ChIJexisting',
    place_snapshot: null,
    external_url: null,
    vote_summary: null,
    comment_count: 0,
    distances: [],
    children: [],
    created_at: '2027-01-01T00:00:00Z',
    updated_at: '2027-01-01T00:00:00Z',
    ...overrides,
  }
}

function baseProps() {
  return {
    onClose: vi.fn(),
    onCreated: vi.fn(),
    pendingClick: null,
    onConsumeClick: vi.fn(),
    existingSuggestions: [] as Suggestion[],
    onFocusExisting: vi.fn(),
    onModeChange: vi.fn(),
  }
}

describe('CreateSuggestionForm — the Places ToS invariant', () => {
  it('never sends Google-sourced detail fields (photos, rating, hours) to the server on create', async () => {
    getPlaceDetails.mockResolvedValue({
      placeId: 'ChIJabc',
      name: 'Harbour House Cottages',
      address: '1 Harbour Rd, Cornwall',
      lat: 50.42,
      lng: -4.74,
      photoUrls: ['https://maps.googleapis.com/photo1.jpg', 'https://maps.googleapis.com/photo2.jpg'],
      rating: 4.7,
      openingHoursText: ['Mon-Sun: 24 hours'],
    })
    autocompletePlaces.mockResolvedValue([{ placeId: 'ChIJabc', description: 'Harbour House Cottages, Cornwall' }])

    const props = baseProps()
    render(<CreateSuggestionForm {...props} />)

    fireEvent.change(screen.getByLabelText('Search for a place'), { target: { value: 'Harbour' } })
    await waitFor(() => expect(screen.getByText('Harbour House Cottages, Cornwall')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Harbour House Cottages, Cornwall'))
    await waitFor(() => expect(screen.getByLabelText('Title')).toHaveValue('Harbour House Cottages'))

    fireEvent.click(screen.getByRole('button', { name: 'Save suggestion' }))
    await waitFor(() => expect(create).toHaveBeenCalled())

    const sentBody = create.mock.calls[0][0] as Record<string, unknown>
    expect(sentBody.place_id).toBe('ChIJabc')
    expect(sentBody).not.toHaveProperty('photos')
    expect(sentBody).not.toHaveProperty('photoUrls')
    expect(sentBody).not.toHaveProperty('rating')
    expect(sentBody).not.toHaveProperty('opening_hours')
    expect(sentBody).not.toHaveProperty('openingHoursText')
    // The real POST /suggestions schema has no trip_id field and rejects one (422,
    // `extra = "forbid"`) — found by the M3 integration pass's live Playwright smoke.
    expect(sentBody).not.toHaveProperty('trip_id')
    // Only the user-authored snapshot travels, per the HARD INVARIANT — never the raw
    // Google response.
    expect(sentBody.place_snapshot).toEqual({ name: 'Harbour House Cottages', address: '1 Harbour Rd, Cornwall' })
  })
})

describe('CreateSuggestionForm — drop pin', () => {
  it('places the pin from a consumed map click and requires no Google call', async () => {
    create.mockResolvedValue(suggestion())
    const props = baseProps()
    // The mode comes from the entry point now (right-click → "Drop a pin here"); there is no
    // in-form tab to click.
    const { rerender } = render(<CreateSuggestionForm {...props} initialMode="drop-pin" />)

    expect(screen.getByText('Click anywhere on the map to drop the pin.')).toBeInTheDocument()

    rerender(<CreateSuggestionForm {...props} initialMode="drop-pin" pendingClick={{ lat: 51.1, lng: 0.2 }} />)
    await waitFor(() => expect(props.onConsumeClick).toHaveBeenCalled())
    expect(screen.getByText(/Pin placed at 51.1000, 0.2000/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Our campsite' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save suggestion' }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    const sentBody = create.mock.calls[0][0] as Record<string, unknown>
    expect(sentBody.lat).toBe(51.1)
    expect(sentBody.lng).toBe(0.2)
    expect(sentBody.place_id).toBeUndefined()
  })

  it('opens in the mode its entry point chose (M3 integration-pass fix)', () => {
    // Found by the live Playwright smoke: MapSuggestionsScreen tracked which entry point was
    // used but never told this component, so every one of them silently opened in search mode.
    // The tabs that once expressed this are gone (2026-08-12 — every entry point now decides
    // the mode by gesture), so the assertion moved from "which tab is selected" to what the
    // mode actually produces: the drop-pin instruction, and no search field.
    const props = baseProps()
    render(<CreateSuggestionForm {...props} initialMode="drop-pin" />)
    expect(screen.getByText('Click anywhere on the map to drop the pin.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Search for a place')).not.toBeInTheDocument()
  })

  it('reports its mode to the parent, which gates map clicks on it', () => {
    // `MapSuggestionsScreen.onMapClick` only forwards a click while its own `createMode` says
    // drop-pin/draw-region, and it learns that from this callback — so a form that never
    // reported its mode would make drop-pin impossible even though the mode was correct here.
    // (This once also covered switching tabs by hand; that path is gone with the tabs, but the
    // report itself is still load-bearing.)
    const props = baseProps()
    render(<CreateSuggestionForm {...props} initialMode="drop-pin" />)
    expect(props.onModeChange).toHaveBeenCalledWith('drop-pin')
  })
})

describe('CreateSuggestionForm — validation', () => {
  it('refuses to save without a title', async () => {
    const props = baseProps()
    render(<CreateSuggestionForm {...props} pendingClick={{ lat: 1, lng: 1 }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Save suggestion' }))
    expect(await screen.findByText('Give this a title.')).toBeInTheDocument()
    expect(create).not.toHaveBeenCalled()
  })
})

describe('CreateSuggestionForm — duplicate place warning', () => {
  it('warns, but does not block, when an accommodation with the same place_id already exists', async () => {
    getPlaceDetails.mockResolvedValue({
      placeId: 'ChIJexisting',
      name: 'Existing place',
      address: 'Somewhere',
      lat: 50.4,
      lng: -4.7,
      photoUrls: [],
      rating: null,
      openingHoursText: null,
    })
    autocompletePlaces.mockResolvedValue([{ placeId: 'ChIJexisting', description: 'Existing place' }])

    const props = baseProps()
    props.existingSuggestions = [suggestion({ place_id: 'ChIJexisting' })]
    render(<CreateSuggestionForm {...props} />)

    fireEvent.change(screen.getByLabelText('Search for a place'), { target: { value: 'Existing' } })
    await waitFor(() => expect(screen.getByText('Existing place')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Existing place'))

    expect(await screen.findByText(/Someone already suggested this place/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save suggestion' })).toBeEnabled()
  })
})
