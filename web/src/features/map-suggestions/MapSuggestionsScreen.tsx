/**
 * The map-suggestions screen — **map-first** (revised 2026-08-12, `design.md` > "Layout").
 *
 * The map fills the content area. Search, filters, the list, a suggestion's detail and the
 * create form are all summoned over it and dismissed again; nothing is permanently docked
 * beside it. The old 62/38 split spent a third of the window on a filter row and a line of
 * placeholder text even on a trip with no suggestions at all, while squeezing the one
 * surface every create gesture starts from.
 *
 * Three ways in, all on the map: the toolbar's search field, right-click → "Drop a pin
 * here", and clicking a place Google already draws (we suppress Google's own info window and
 * show `PlacePreviewCard` instead, because that window takes no custom actions). Map and
 * list remain one dataset behind `suggestionStore`: selecting anywhere updates both.
 *
 * Follows `FamiliesScreen`/`PollsScreen`'s convention of owning its whole layout inside the
 * screen rather than through `Shell`'s `sidePanel` prop — neither existing feature uses that
 * slot, so matching them keeps one convention rather than introducing a second, even though
 * `shell.tsx`'s own comment reads as if a feature eventually would.
 *
 * Progressive disclosure (`design.md`): a marker click selects the suggestion, which opens
 * the full detail (level 3) in a card over the map. That card floats at the map's edge
 * rather than being tethered to its pin, because `MapProvider` (`features/map/MapProvider.ts`)
 * still has no lat/lng → screen-point query to anchor against; a genuinely anchored popover
 * remains a known follow-up, and the interface — not this screen — is where it has to be
 * fixed. On mobile, where the constraint is screen space rather than an anchor point, the two
 * levels *are* real: `BottomSheet`'s `peek` snap renders the real `PopoverCard` (level 2) and
 * `full` renders `SuggestionDetailPanel` (level 3, `design.md` S10).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useSession } from '../../app/session'
import { useStage } from '../../app/useStage'
import { BottomSheet } from '../../app/BottomSheet'
import { Banner, Button, Skeleton } from '../../app/ui/primitives'
import { PANEL_SHEET_QUERY } from '../../design/breakpoints'
import { MapCanvas } from '../map/MapCanvas'
import { GoogleMapProvider } from '../map/GoogleMapProvider'
import { createFakeMapProvider } from '../map/FakeMapProvider'
import { PopoverCard } from '../map/PopoverCard'
import type { LatLng } from '../map/types'
import type { MapProvider } from '../map/MapProvider'
import { suggestionStore, useSuggestionView } from './store'
import { useSuggestionList } from './useSuggestions'
import { suggestionMarkers, regionPolygons } from './markers'
import { FilterMenu } from './FilterMenu'
import { MapSearchField } from './MapSearchField'
import { MapContextMenu } from './MapContextMenu'
import { PlacePreviewCard } from './PlacePreviewCard'
import { getPlaceDetails, placesAvailable } from './placesClient'
import type { PlaceDetails } from './placesClient'
import { PlaceProfilePanel } from './PlaceProfilePanel'
import { useAnchoredPlacement } from './useAnchoredPlacement'
import { SIDE_PANEL_SLOT_ID, setSidePanelFilled } from '../../app/sidePanelSlot'
import { createPortal } from 'react-dom'
import { SuggestionsList } from './SuggestionsList'
import { SuggestionDetailPanel } from './SuggestionDetailPanel'
import { CreateSuggestionForm } from './CreateSuggestionForm'
import type { CreateMode, PlaceSeed } from './CreateSuggestionForm'
import { SuggestionVotePanel } from '../voting-comments/SuggestionVotePanel'
import { usePendingVotes } from '../voting-comments/usePendingVotes'
import { DistanceChip } from '../distances/DistanceChip'
import { distanceForFamily } from '../distances/distanceOrder'
import type { Suggestion } from '../../app/types'
import './mapSuggestions.css'

const CATEGORY_LABEL: Record<Suggestion['type'], string> = {
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
  other: 'Other',
  region: 'Region',
}

const DEFAULT_CENTER: LatLng = { lat: 51.5, lng: -0.12 }

/** `GoogleMapProvider` throws immediately when no key is configured (its own docblock);
 * catching that here is what turns a missing key into the empty state `design.md`'s
 * edge-case table asks for ("Map area shows an explanatory empty state; the list view
 * remains fully functional") instead of an unhandled render crash. */
function createMapProvider() {
  const key = import.meta.env.VITE_GOOGLE_MAPS_BROWSER_KEY as string | undefined
  if (key) return new GoogleMapProvider()
  // Dev/test fallback with no key configured, per this feature's own note on running
  // against mock data ahead of a configured key — `FakeMapProvider` is the sanctioned
  // stand-in the pre-built shell ships for exactly this.
  return createFakeMapProvider()
}

function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(PANEL_SHEET_QUERY).matches ?? false)
  useEffect(() => {
    const query = window.matchMedia?.(PANEL_SHEET_QUERY)
    if (!query) return
    const update = () => setNarrow(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return narrow
}

/** Renders into the shell's right-hand panel, and tells the shell so — otherwise its
 *  "select something…" placeholder would sit above whatever we portal in. */
function SidePanelPortal({ children }: { children: React.ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  useEffect(() => {
    // The slot is the shell's DOM, mounted before any screen inside it; looked up on mount
    // rather than held in a ref because this component and the shell are siblings in the
    // tree, not parent and child.
    setSlot(document.getElementById(SIDE_PANEL_SLOT_ID))
  }, [])
  useEffect(() => {
    setSidePanelFilled(true)
    return () => setSidePanelFilled(false)
  }, [])
  return slot ? createPortal(children, slot) : null
}

export function MapSuggestionsScreen({ selectedId }: { selectedId?: string } = {}) {
  const { user, resolvedTheme } = useSession()
  const stage = useStage()
  const view = useSuggestionView()
  const narrow = useIsNarrow()
  const tripId = user?.trip?.id ?? null

  const listParams = useMemo(() => {
    if (!tripId) return null
    return {
      trip_id: tripId,
      type: view.filters.types.length ? view.filters.types : undefined,
      status: view.filters.statuses.length ? view.filters.statuses : undefined,
      family_id: view.filters.familyIds.length ? view.filters.familyIds : undefined,
      sort: view.sort ? (`${view.sort.field}_${view.sort.dir}` as const) : undefined,
    }
  }, [tripId, view.filters, view.sort])

  // Sorting/filtering are applied server-side (`sort` query param); grouped children stay
  // nested under their parent and travel with it (`design.md`: "the list endpoint returns
  // children nested ... and omits them from the top level").
  const { suggestions: fetched, loading, error, upsert, remove } = useSuggestionList(listParams)

  // "Needs my vote" (voting-comments V5/Phase 10) has no server list param — the shared
  // filter store's `needsMyVote` flag intersects the already-fetched page with
  // `GET /me/pending-votes`'s id set client-side, same reasoning as the store's own doc
  // comment on why this one filter differs from the rest.
  const pendingVotes = usePendingVotes(tripId)
  const sorted = view.filters.needsMyVote
    ? fetched.filter((s) => pendingVotes.suggestion_ids.includes(s.id))
    : fetched

  // Deep link support (`/map/:suggestionId`): a one-way sync into the shared store on
  // mount/navigation. Selecting from the map or list does not push a URL change back — a
  // full two-way sync is deferred, noted in this feature's handoff.
  useEffect(() => {
    if (selectedId) suggestionStore.select(selectedId)
  }, [selectedId])

  const [creating, setCreating] = useState(false)
  const [createMode, setCreateMode] = useState<CreateMode>('search')
  const [pendingClick, setPendingClick] = useState<LatLng | null>(null)
  const [mobileSnap, setMobileSnap] = useState<'peek' | 'full'>('peek')
  const [mobileListOpen, setMobileListOpen] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const [seedPlace, setSeedPlace] = useState<PlaceSeed | null>(null)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; position: LatLng } | null>(null)
  // The Google POI the user clicked, resolving or resolved. Distinct from `seedPlace`: this
  // one is only being *looked at*; it becomes a seed if they press "Add as suggestion".
  const [poi, setPoi] = useState<{
    placeId: string
    loading: boolean
    /** The full Places record — the profile panel shows what Google shows. */
    details: PlaceDetails | null
    error: string | null
  } | null>(null)
  const mapAreaRef = useRef<HTMLDivElement | null>(null)
  const providerRef = useRef<MapProvider | null>(null)
  /** Where the POI card is pinned, in container pixels. `null` = not projectable yet, which
   *  is a real state on the tick the map mounts — the card waits rather than jumping. */
  const [poiPoint, setPoiPoint] = useState<{ x: number; y: number } | null>(null)
  /** Where the pointer last was inside the map area, in container pixels — the only thing
   *  the context menu needs that a `LatLng` cannot give it. */
  const lastPointerPointRef = useRef({ x: 0, y: 0 })
  const [flyTo, setFlyTo] = useState<LatLng | null>(null)

  const selected = view.selectedId ? sorted.flatMap((s) => [s, ...s.children]).find((s) => s.id === view.selectedId) : null

  const markers = useMemo(() => suggestionMarkers(sorted, view.selectedId), [sorted, view.selectedId])
  const polygons = useMemo(() => regionPolygons(sorted, view.selectedId), [sorted, view.selectedId])

  const onMarkerClick = useCallback(({ id }: { id: string }) => {
    suggestionStore.select(id)
    setMobileSnap('peek')
    setMobileListOpen(false)
  }, [])

  const onMapClick = useCallback(
    ({ position, placeId }: { position: LatLng; placeId?: string }) => {
      setContextMenu(null)
      if (creating && (createMode === 'drop-pin' || createMode === 'draw-region')) {
        setPendingClick(position)
        return
      }
      // A click on one of Google's own labelled places. Its info window has already been
      // suppressed by the provider, so what we show is the only thing the user sees — showing
      // nothing here would make those places read as dead.
      if (!placeId) return
      if (!placesAvailable()) {
        setPoi({ placeId, loading: false, details: null, error: 'Place details are unavailable right now.' })
        return
      }
      // Clicking a place dismisses whatever was open first. Only one thing on this map is
      // ever "the thing you are looking at", and the click just said which — leaving the old
      // card up meant two anchored surfaces fighting over one position, with the open form
      // sliding to a place the user had not chosen.
      setCreating(false)
      setSeedPlace(null)
      setPendingClick(null)
      suggestionStore.select(null)
      setPoi({ placeId, loading: true, details: null, error: null })
      void getPlaceDetails(placeId)
        .then((details) => setPoi({ placeId, loading: false, error: null, details }))
        .catch(() =>
          setPoi({ placeId, loading: false, details: null, error: 'That place could not be loaded.' }),
        )
    },
    [creating, createMode],
  )

  const onMapContextMenu = useCallback(({ position }: { position: LatLng }) => {
    // Pixels come from the DOM event captured on the wrapper below, not from the provider —
    // see `MapContextMenu`'s docblock for why the interface is not grown for this.
    const point = lastPointerPointRef.current
    setPoi(null)
    setContextMenu({ x: point.x, y: point.y, position })
  }, [])

  function openCreate(mode: CreateMode, seed: PlaceSeed | null = null) {
    setCreateMode(mode)
    setSeedPlace(seed)
    setCreating(true)
    setListOpen(false)
    setPoi(null)
    setContextMenu(null)
  }

  /**
   * Re-pins the POI card over the place it describes. Runs on every `viewChange` (Google
   * fires `bounds_changed` continuously through a drag, so the card travels with the map
   * instead of catching up at the end) and whenever the POI itself changes.
   *
   * A `null` projection means the SDK cannot answer yet; the card then falls back to its
   * corner position rather than being placed at a guessed 0,0.
   */
  const reprojectPoi = useCallback(() => {
    const position = poiPositionRef.current
    if (!position) {
      setPoiPoint(null)
      return
    }
    setPoiPoint(providerRef.current?.projectToContainerPoint(position) ?? null)
  }, [])

  // One anchor for everything the map speaks through: the POI being previewed, or — once the
  // user commits to suggesting it — the point the create form is about. Keeping them on the
  // same anchor is what makes the form look like the card expanding in place rather than a
  // second, unrelated surface opening somewhere else.
  const anchorPosition =
    (poi?.details ? { lat: poi.details.lat, lng: poi.details.lng } : null) ??
    seedPlace?.position ??
    pendingClick ??
    null
  const poiPositionRef = useRef<LatLng | null>(null)
  poiPositionRef.current = anchorPosition

  useEffect(() => {
    reprojectPoi()
  }, [anchorPosition?.lat, anchorPosition?.lng, reprojectPoi])

  /** Right-click → "Drop a pin here": open the form already holding that point, so the
   *  gesture completes in one step instead of asking for a second click on the map. */
  function createAt(position: LatLng, mode: Extract<CreateMode, 'drop-pin' | 'draw-region'>) {
    openCreate(mode)
    setPendingClick(position)
  }

  if (!tripId) {
    return (
      <div className="map-suggestions">
        <Banner tone="info">No trip yet — suggestions arrive once the trip is set up.</Banner>
      </div>
    )
  }

  const panelBody = (onBack?: () => void) =>
    selected ? (
      <SuggestionDetailPanel
        suggestion={selected}
        onChanged={upsert}
        onDeleted={(id) => {
          remove(id)
          suggestionStore.select(null)
        }}
        onBack={onBack}
        // Deselecting reveals the list only if the drawer is open behind this card; from a
        // pin click it dismisses to the map, and the button says which.
        backLabel={listOpen ? '← Back to list' : '← Back to the map'}
      />
    ) : (
      <>
        {loading ? (
          <div aria-busy="true" className="map-suggestions__skeleton">
            <Skeleton height="var(--space-6)" />
            <Skeleton height="var(--space-6)" />
            <Skeleton height="var(--space-6)" />
          </div>
        ) : error ? (
          <Banner tone="error">{error}</Banner>
        ) : (
          <SuggestionsList
            suggestions={sorted}
            tripId={tripId}
            ownFamilyId={user?.family?.id ?? null}
            onCreate={() => openCreate('url', null)}
          />
        )}
      </>
    )

  /** What belongs in the shell's panel right now: a selected suggestion's detail, or the
   *  list when it was asked for. The create form is not here — see its own comment below. */
  const sidePanelContent = poi && !creating ? (
    // A clicked Google place, shown the way Google shows it (`PlaceProfilePanel`). It takes
    // precedence over the list because it is what the user just did.
    <PlaceProfilePanel
      place={poi.details}
      loading={poi.loading}
      error={poi.error}
      canAdd={stage.canMutate}
      onAdd={(seed) => openCreate('search', seed)}
      onClose={() => setPoi(null)}
    />
  ) : selected ? (
    panelBody(() => suggestionStore.select(null))
  ) : listOpen ? (
    <>
      <div className="map-suggestions__panel-header">
        <h2 className="map-suggestions__panel-title">Suggestions</h2>
        <button type="button" onClick={() => setListOpen(false)} aria-label="Close list">
          ×
        </button>
      </div>
      {panelBody()}
    </>
  ) : null
  /** The projected anchor, but only while the create form is the thing being anchored. */
  const createAnchorPoint = creating ? poiPoint : null
  // Both anchored surfaces flip below their point and clamp to the map's box rather than
  // hanging off an edge — a card you cannot read is not anchored, it is lost.
  const poiPlacement = useAnchoredPlacement(poi && !creating ? poiPoint : null, mapAreaRef.current)
  const formPlacement = useAnchoredPlacement(createAnchorPoint, mapAreaRef.current)

  return (
    <div className={`map-suggestions${narrow ? ' map-suggestions--narrow' : ''}`}>
      <div
        className="map-suggestions__map"
        ref={mapAreaRef}
        onPointerDown={(event) => {
          const rect = mapAreaRef.current?.getBoundingClientRect()
          lastPointerPointRef.current = {
            x: event.clientX - (rect?.left ?? 0),
            y: event.clientY - (rect?.top ?? 0),
          }
        }}
        onContextMenu={(event) => {
          // The browser menu is never what the user wants over a map, and Google's own
          // surface does not suppress it for us on every provider.
          event.preventDefault()
        }}
      >
        <div className="map-suggestions__toolbar">
          <MapSearchField
            onPick={(seed) => {
              setFlyTo(seed.position)
              // Picked from the toolbar's search: the place is decided, so the tabs have
              // nothing left to ask either.
              openCreate('search', seed)
            }}
          />
          <FilterMenu />
          <button
            type="button"
            className="map-suggestions__list-toggle"
            aria-pressed={listOpen}
            onClick={() => {
              setListOpen((open) => !open)
              suggestionStore.select(null)
              setCreating(false)
            }}
          >
            List ({sorted.length})
          </button>
          {/* Every other way in now lives on the map itself: search is the field to the left,
              drop-a-pin and draw-a-region are on right-click. What the map cannot do is take
              a URL — an Airbnb listing or a shop's website is not a thing you can point at —
              so that is what this button is for, and it says so. */}
          <Button onClick={() => openCreate('url', null)} disabled={!stage.canMutate}>
            Paste a link
          </Button>
          {creating ? (
            <span className="map-suggestions__hint" aria-live="polite">
              {createMode === 'drop-pin'
                ? 'Click the map to drop a pin.'
                : createMode === 'draw-region'
                  ? 'Click the map to draw a region.'
                  : null}
            </span>
          ) : null}
        </div>
        <MapCanvas
          // Remount on a theme change: Google fixes `colorScheme` at construction, so this
          // key is what makes "the map follows the app's theme" true (`MapMountOptions`).
          key={resolvedTheme}
          createProvider={createMapProvider}
          colorScheme={resolvedTheme}
          center={flyTo ?? (selected ? { lat: selected.lat, lng: selected.lng } : DEFAULT_CENTER)}
          zoom={12}
          markers={markers}
          polygons={polygons}
          onMarkerClick={onMarkerClick}
          onPolygonClick={onMarkerClick}
          onMapClick={onMapClick}
          onMapContextMenu={onMapContextMenu}
          onProviderReady={(provider) => {
            providerRef.current = provider
          }}
          onViewChange={reprojectPoi}
        />

        {contextMenu ? (
          <MapContextMenu
            x={contextMenu.x}
            y={contextMenu.y}
            disabled={!stage.canMutate}
            onDropPin={() => createAt(contextMenu.position, 'drop-pin')}
            onDrawRegion={() => createAt(contextMenu.position, 'draw-region')}
            onClose={() => setContextMenu(null)}
          />
        ) : null}

        {/* Never while the create form is open: a place-click re-seeds that form instead
            (see `onMapClick`), so there is only ever one anchored card on the map. */}
        {poi && !creating ? (
          <div
            ref={poiPlacement.ref}
            className={[
              'map-suggestions__poi',
              poiPlacement.placement ? 'map-suggestions__poi--anchored' : '',
              poiPlacement.placement?.below ? 'is-below' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            style={
              poiPlacement.placement
                ? ({
                    left: `${poiPlacement.placement.left}px`,
                    top: `${poiPlacement.placement.top}px`,
                    '--tail-x': `${poiPlacement.placement.tailX}px`,
                  } as CSSProperties)
                : undefined
            }
          >
            <PlacePreviewCard
              place={
                poi.details
                  ? {
                      placeId: poi.details.placeId,
                      name: poi.details.name,
                      address: poi.details.address,
                      position: { lat: poi.details.lat, lng: poi.details.lng },
                      types: poi.details.types,
                    }
                  : null
              }
              loading={poi.loading}
              error={poi.error}
              canAdd={stage.canMutate}
              anchored={Boolean(poiPoint)}
              // Desktop reads the place in the side panel; this card only says which pin was
              // clicked. Mobile has no side panel, so there the card keeps the actions.
              showActions={narrow}
              onAdd={(place) => openCreate('search', place)}
              onClose={() => setPoi(null)}
            />
          </div>
        ) : null}

        {/* The create form only. It is about one point on the map, so it opens *at* that
            point rather than in the shell's panel — the POI card growing into a form. */}
        {!narrow && creating ? (
          <aside
            className={[
              'map-suggestions__panel',
              'map-suggestions__panel--form',
              formPlacement.placement ? 'map-suggestions__panel--anchored' : '',
              formPlacement.placement?.below ? 'is-below' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            ref={formPlacement.ref}
            style={
              formPlacement.placement
                ? ({
                    left: `${formPlacement.placement.left}px`,
                    top: `${formPlacement.placement.top}px`,
                    '--tail-x': `${formPlacement.placement.tailX}px`,
                  } as CSSProperties)
                : undefined
            }
            aria-label="Suggest a place"
          >
            <CreateSuggestionForm
              initialMode={createMode}
              onModeChange={setCreateMode}
              seedPlace={seedPlace}
              onClose={() => {
                setCreating(false)
                setPendingClick(null)
                setSeedPlace(null)
              }}
              onCreated={(created) => {
                upsert(created)
                suggestionStore.select(created.id)
                setCreating(false)
                setSeedPlace(null)
              }}
              pendingClick={pendingClick}
              onConsumeClick={() => setPendingClick(null)}
              existingSuggestions={sorted}
              onFocusExisting={(id) => {
                setCreating(false)
                suggestionStore.select(id)
              }}
            />
          </aside>
        ) : null}
      </div>

      {/* Detail and list live in the shell's own right-hand panel. Floating them over the
          map put a card on top of the thing it describes while an empty column beside it
          invited the user to select something — the panel exists, so this screen fills it. */}
      {!narrow && sidePanelContent ? <SidePanelPortal>{sidePanelContent}</SidePanelPortal> : null}

      {!narrow ? null : (
        <>
          <button
            type="button"
            className="map-suggestions__list-fab"
            onClick={() => setMobileListOpen(true)}
            aria-label="Show list"
          >
            List ({sorted.length})
          </button>

          <BottomSheet
            open={Boolean(selected)}
            title={selected?.title ?? 'Suggestion'}
            onClose={() => suggestionStore.select(null)}
            initialSnap={mobileSnap}
          >
            {selected && mobileSnap === 'peek' ? (
              <PopoverCard
                title={selected.title}
                category={selected.type}
                status={selected.status}
                commentCount={selected.comment_count}
                voteSummary={
                  // Voting is available from the popover card, not only the panel
                  // (`design.md`: "a quick pass over many pins is a real workflow").
                  <SuggestionVotePanel
                    suggestionId={selected.id}
                    suggestionType={selected.type}
                    title={selected.title}
                    density="medium"
                    canVote={Boolean(user) && stage.canMutate}
                    controlSize="compact"
                  />
                }
                distanceChips={
                  // Popover stays glanceable — the caller's own family only (`design.md` >
                  // "Placement"); the full per-family breakdown lives in the panel.
                  (() => {
                    const own = distanceForFamily(selected.distances, user?.family?.id ?? null)
                    return own ? <DistanceChip distance={own} isRegion={selected.type === 'region'} /> : null
                  })()
                }
                onDetails={() => setMobileSnap('full')}
              />
            ) : (
              selected && panelBody()
            )}
          </BottomSheet>

          <BottomSheet open={mobileListOpen && !selected} title="Suggestions" onClose={() => setMobileListOpen(false)}>
            {panelBody()}
          </BottomSheet>
        </>
      )}

      {/* Mobile only: on desktop the form now renders inside the side panel above, beside
          the map rather than over it — a full-screen overlay here made drop-pin/draw-region
          structurally impossible (the smoke that caught it: `01-map-suggestions.spec.ts`),
          because its backdrop intercepted every click meant for the map underneath.
          `BottomSheet`'s own backdrop has the identical property (`.sheet-backdrop`,
          `position: absolute; inset: 0`) and blocking clicks on it is *also* its job when it
          is showing a suggestion's details — so drop-pin/draw-region on mobile keep this
          known limitation for now; a non-blocking peek affordance for that one flow is a
          real follow-up, not something to redesign inline here. */}
      {narrow && creating ? (
        <div className="map-suggestions__create-overlay">
          <CreateSuggestionForm
            initialMode={createMode}
            onModeChange={setCreateMode}
            // The toolbar's search field and the POI card are on the map at every width, so
            // the seed has to reach this copy of the form too — without it a mobile user who
            // picked a place watched the form open empty and had to search for it again.
            seedPlace={seedPlace}
            onClose={() => {
              setCreating(false)
              setPendingClick(null)
              setSeedPlace(null)
            }}
            onCreated={(created) => {
              upsert(created)
              suggestionStore.select(created.id)
              setSeedPlace(null)
            }}
            pendingClick={pendingClick}
            onConsumeClick={() => setPendingClick(null)}
            existingSuggestions={sorted}
            onFocusExisting={(id) => {
              setCreating(false)
              suggestionStore.select(id)
            }}
          />
        </div>
      ) : null}
    </div>
  )
}

export { CATEGORY_LABEL }
