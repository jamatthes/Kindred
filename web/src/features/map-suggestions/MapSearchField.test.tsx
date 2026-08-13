/**
 * The map toolbar's place search (`design.md` > "Map-first interaction model", 1).
 *
 * Three promises to keep. It resolves Place Details **once**, here, and hands the whole seed
 * up — the parent flies the map and seeds the create form from that one result, so a second
 * billed lookup would be a real regression, not a style point. It carries the guessed type's
 * raw input (`types`) with it. And with no Places SDK it disables itself and says where to go
 * instead, rather than swallowing keystrokes into a search that can never return.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MapSearchField } from './MapSearchField'
import { autocompletePlaces, getPlaceDetails, placesAvailable } from './placesClient'

vi.mock('./placesClient', () => ({
  placesAvailable: vi.fn(() => true),
  autocompletePlaces: vi.fn(),
  getPlaceDetails: vi.fn(),
}))

const mockAvailable = vi.mocked(placesAvailable)
const mockAutocomplete = vi.mocked(autocompletePlaces)
const mockDetails = vi.mocked(getPlaceDetails)

const DETAILS = {
  placeId: 'place-1',
  name: 'Watergate Bay',
  address: 'Newquay',
  lat: 50.44,
  lng: -5.04,
  editorialSummary: null,
  photoUrls: [],
  rating: null,
  openingHoursText: null,
    website: null,
    phone: null,
    ratingCount: null,
    openNow: null,
  types: ['lodging'],
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mockAvailable.mockReturnValue(true)
  mockAutocomplete.mockResolvedValue([
    { placeId: 'place-1', description: 'Watergate Bay Hotel', types: ['lodging'] },
  ])
  mockDetails.mockResolvedValue(DETAILS)
})

afterEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
})

async function typeAndPick(onPick = vi.fn()) {
  render(<MapSearchField onPick={onPick} />)
  fireEvent.change(screen.getByLabelText('Search for a place'), { target: { value: 'watergate' } })
  await vi.advanceTimersByTimeAsync(300)
  fireEvent.click(await screen.findByRole('button', { name: 'Watergate Bay Hotel' }))
  return onPick
}

describe('MapSearchField', () => {
  it('debounces: one autocomplete request for a burst of keystrokes', async () => {
    render(<MapSearchField onPick={vi.fn()} />)
    const input = screen.getByLabelText('Search for a place')
    fireEvent.change(input, { target: { value: 'wat' } })
    fireEvent.change(input, { target: { value: 'water' } })
    fireEvent.change(input, { target: { value: 'watergate' } })

    await vi.advanceTimersByTimeAsync(300)
    expect(mockAutocomplete).toHaveBeenCalledTimes(1)
    expect(mockAutocomplete).toHaveBeenCalledWith('watergate')
  })

  it('picking a prediction resolves details once and hands the seed up whole', async () => {
    const onPick = await typeAndPick()

    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1))
    expect(mockDetails).toHaveBeenCalledTimes(1)
    expect(onPick).toHaveBeenCalledWith({
      placeId: 'place-1',
      name: 'Watergate Bay',
      address: 'Newquay',
      position: { lat: 50.44, lng: -5.04 },
      // Carried, not dropped: this array is the only input the create form's type guess has.
      types: ['lodging'],
    })
  })

  it("falls back to the prediction's own categories when Details came back without any", async () => {
    mockDetails.mockResolvedValue({ ...DETAILS, types: [] })
    const onPick = await typeAndPick()
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ types: ['lodging'] })))
  })

  it('clears the field and the results after a pick, so the toolbar is ready for the next one', async () => {
    await typeAndPick()
    await waitFor(() => expect(screen.getByLabelText('Search for a place')).toHaveValue(''))
    expect(screen.queryByRole('button', { name: 'Watergate Bay Hotel' })).not.toBeInTheDocument()
  })

  it('says so when Details fails, and points at the gesture that still works', async () => {
    mockDetails.mockRejectedValue(new Error('places down'))
    const onPick = await typeAndPick()

    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument()
    expect(onPick).not.toHaveBeenCalled()
  })

  it('disables itself with no Places SDK rather than swallowing every keystroke', async () => {
    mockAvailable.mockReturnValue(false)
    render(<MapSearchField onPick={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search for a place'), { target: { value: 'watergate' } })

    await vi.advanceTimersByTimeAsync(300)
    expect(mockAutocomplete).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Search for a place')).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('right-click the map to drop a pin instead')
  })
})
