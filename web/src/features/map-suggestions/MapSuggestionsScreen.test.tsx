/**
 * The map-first screen's own wiring (`tasks.md` Phase 13, item 4).
 *
 * Everything below the screen — the form, the list, the detail panel — has its own tests and
 * is stubbed here. What only this file can check is the trade the redesign made: the map is
 * never covered by anything the user did not ask for, and each of the three summonable
 * surfaces (list drawer, POI card, context menu) opens, closes, and hands the *right thing*
 * to the create form. A seed that arrives empty is the exact failure the old always-on panel
 * could not have, so it is the one worth a test.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MapSuggestionsScreen } from './MapSuggestionsScreen'
import { suggestionStore } from './store'
import { SIDE_PANEL_SLOT_ID } from '../../app/sidePanelSlot'
import { getPlaceDetails, placesAvailable } from './placesClient'
import type { MapCanvasProps } from '../map/MapCanvas'
import type { Suggestion } from '../../app/types'

function suggestion(overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 's1',
    type: 'accommodation',
    title: 'Harbour House',
    notes: null,
    status: 'proposed',
    created_by: { user_id: 'u1', display_name: 'Alex', family_id: 'f1', family_color: 3, family_color_custom: null },
    lat: 50.4,
    lng: -4.7,
    geometry_geojson: null,
    place_id: null,
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

vi.mock('../../app/session', () => ({
  useSession: () => ({
    user: { trip: { id: 't1', stage: 'planning' }, family: { id: 'f1' } },
    resolvedTheme: 'light',
  }),
}))

vi.mock('./useSuggestions', () => ({
  useSuggestionList: () => ({
    suggestions: [suggestion()],
    loading: false,
    error: null,
    upsert: vi.fn(),
    remove: vi.fn(),
  }),
}))

vi.mock('../voting-comments/usePendingVotes', () => ({
  usePendingVotes: () => ({ suggestion_ids: [] }),
}))

vi.mock('../families/useFamilies', () => ({
  useFamilies: () => ({ families: [], loading: false, error: null }),
}))

vi.mock('./placesClient', () => ({
  placesAvailable: vi.fn(() => true),
  autocompletePlaces: vi.fn(async () => []),
  getPlaceDetails: vi.fn(),
}))

/** The map, reduced to the two gestures this screen has to answer. `FakeMapProvider` cannot
 *  stand in here: it draws no base map, so it has no Google POI to click. */
let fireMapClick: MapCanvasProps['onMapClick']
let fireContextMenu: MapCanvasProps['onMapContextMenu']
vi.mock('../map/MapCanvas', () => ({
  MapCanvas: (props: MapCanvasProps) => {
    fireMapClick = props.onMapClick
    fireContextMenu = props.onMapContextMenu
    return <div data-testid="map-canvas" />
  },
}))

vi.mock('./SuggestionsList', () => ({
  SuggestionsList: () => <div data-testid="suggestions-list" />,
}))
vi.mock('./SuggestionDetailPanel', () => ({
  SuggestionDetailPanel: () => <div data-testid="detail-panel" />,
}))
vi.mock('./CreateSuggestionForm', () => ({
  CreateSuggestionForm: (props: { initialMode: string; seedPlace?: { name: string } | null }) => (
    <div data-testid="create-form" data-mode={props.initialMode}>
      {props.seedPlace?.name ?? 'no seed'}
    </div>
  ),
}))

const mockDetails = vi.mocked(getPlaceDetails)
const mockAvailable = vi.mocked(placesAvailable)

const POI = {
  placeId: 'place-1',
  name: 'The Minack Theatre',
  address: 'Porthcurno',
  lat: 50.04,
  lng: -5.65,
  editorialSummary: null,
  photoUrls: [],
  rating: null,
  openingHoursText: null,
    website: null,
    phone: null,
    ratingCount: null,
    openNow: null,
  types: ['tourist_attraction'],
}

beforeEach(() => {
  suggestionStore.reset()
  vi.clearAllMocks()
  mockAvailable.mockReturnValue(true)
  mockDetails.mockResolvedValue(POI)
})

/**
 * The list and a suggestion's detail render into the shell's own right-hand panel via a
 * portal (`app/sidePanelSlot.ts`), so a test rendering this screen on its own has to provide
 * the slot the shell would normally have mounted. Without it the portal has nowhere to go and
 * the content simply does not appear — which is a true statement about a screen with no
 * shell, and not what these tests are about.
 */
function withSidePanelSlot(): HTMLElement {
  const slot = document.createElement('div')
  slot.id = SIDE_PANEL_SLOT_ID
  document.body.appendChild(slot)
  return slot
}

describe('MapSuggestionsScreen — what sits over the map', () => {
  it('starts with the map and its toolbar alone: no panel, no list, no card', () => {
    render(<MapSuggestionsScreen />)
    expect(screen.getByTestId('map-canvas')).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Suggestions' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('suggestions-list')).not.toBeInTheDocument()
  })

  it('the List toggle opens the drawer and closes it again', () => {
    withSidePanelSlot()
    render(<MapSuggestionsScreen />)
    const toggle = screen.getByRole('button', { name: /^List/ })
    // The count is on the trigger, so an open drawer is not the only way to learn there is
    // anything in it.
    expect(toggle).toHaveTextContent('List (1)')
    expect(toggle).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(toggle)
    expect(screen.getByTestId('suggestions-list')).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'Close list' }))
    expect(screen.queryByTestId('suggestions-list')).not.toBeInTheDocument()
  })

  it('selecting a suggestion shows its detail instead of the list', () => {
    withSidePanelSlot()
    render(<MapSuggestionsScreen />)
    fireEvent.click(screen.getByRole('button', { name: /^List/ }))
    act(() => suggestionStore.select('s1'))

    expect(screen.getByTestId('detail-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('suggestions-list')).not.toBeInTheDocument()
  })
})

describe('MapSuggestionsScreen — the three ways in', () => {
  it('a POI click opens the place profile, and "Add as suggestion" seeds the create form', async () => {
    // The name appears twice on purpose — as the map's own label on the anchored card, and as
    // the profile's title in the side panel — the same pairing Google Maps uses, so these
    // queries say which surface they mean rather than asserting the name is unique.
    withSidePanelSlot()
    render(<MapSuggestionsScreen />)
    act(() => fireMapClick?.({ position: { lat: 50.04, lng: -5.65 }, placeId: 'place-1' }))

    expect(await screen.findByRole('heading', { level: 2, name: 'The Minack Theatre' })).toBeInTheDocument()
    // Google's own facts, in the panel: the reason this shows a profile and not just a name.
    expect(screen.getAllByText('Porthcurno').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Add as suggestion' }))

    const form = screen.getByTestId('create-form')
    expect(form).toHaveAttribute('data-mode', 'search')
    // The seed reached the form; the details are not fetched a second time.
    expect(form).toHaveTextContent('The Minack Theatre')
    expect(mockDetails).toHaveBeenCalledTimes(1)
  })

  it('a bare map click opens nothing — only Google POIs have a card to show', () => {
    render(<MapSuggestionsScreen />)
    act(() => fireMapClick?.({ position: { lat: 50.4, lng: -4.7 } }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mockDetails).not.toHaveBeenCalled()
  })

  it('says so when Place Details cannot be reached, rather than leaving the POI looking dead', async () => {
    mockAvailable.mockReturnValue(false)
    withSidePanelSlot()
    render(<MapSuggestionsScreen />)
    act(() => fireMapClick?.({ position: { lat: 50.04, lng: -5.65 }, placeId: 'place-1' }))

    expect((await screen.findAllByText(/unavailable right now/)).length).toBeGreaterThan(0)
  })

  it('right-click → "Drop a pin here" opens the form already holding that point', () => {
    render(<MapSuggestionsScreen />)
    act(() => fireContextMenu?.({ position: { lat: 50.4, lng: -4.7 } }))

    fireEvent.click(screen.getByRole('menuitem', { name: 'Drop a pin here' }))
    expect(screen.getByTestId('create-form')).toHaveAttribute('data-mode', 'drop-pin')
    // One gesture, not two: the menu closes and the point is already consumed.
    expect(screen.queryByRole('menu', { name: 'Map actions' })).not.toBeInTheDocument()
  })

  it('opening the context menu dismisses a POI card, so the map never carries both', async () => {
    withSidePanelSlot()
    render(<MapSuggestionsScreen />)
    act(() => fireMapClick?.({ position: { lat: 50.04, lng: -5.65 }, placeId: 'place-1' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'The Minack Theatre' })).toBeInTheDocument()

    act(() => fireContextMenu?.({ position: { lat: 50.4, lng: -4.7 } }))
    expect(screen.queryByRole('heading', { name: 'The Minack Theatre' })).not.toBeInTheDocument()
    expect(screen.getByRole('menu', { name: 'Map actions' })).toBeInTheDocument()
  })
})
