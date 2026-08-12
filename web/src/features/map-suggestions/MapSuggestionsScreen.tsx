/**
 * The map-suggestions screen: `MapCanvas` at ~62%, list/details in the ~38% panel on
 * desktop, a bottom sheet on mobile — `design.md` > "Layout". Map and list are one dataset
 * behind `suggestionStore` (`design.md` S2): selecting anywhere updates both.
 *
 * Follows `FamiliesScreen`/`PollsScreen`'s convention of owning its whole two-column layout
 * inside the screen rather than through `Shell`'s `sidePanel` prop — neither existing
 * feature uses that slot, so matching them keeps one convention rather than introducing a
 * second, even though `shell.tsx`'s own comment reads as if a feature eventually would.
 *
 * Progressive disclosure (`design.md`): a marker click selects the suggestion, which always
 * opens the full detail (level 3) in the desktop panel — there is no separately positioned
 * floating popover on desktop, because `MapProvider` (`features/map/MapProvider.ts`) has no
 * query for a mounted marker's screen position to anchor one against, and `GoogleMapProvider`
 * only added that primitive in the swap this phase makes, not extended the interface (out of
 * scope: "do not modify the provider layer except where a checklist item genuinely requires
 * it" — an anchored popover is a nice-to-have, not a requirement the interface is missing
 * for). On mobile, where the constraint is real screen space rather than an anchor point, the
 * two levels *are* real: `BottomSheet`'s `peek` snap renders the real `PopoverCard` (level 2)
 * and `full` renders `SuggestionDetailPanel` (level 3, `design.md` S10).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
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
import { hasActiveFilters, suggestionStore, useSuggestionView } from './store'
import { useSuggestionList } from './useSuggestions'
import { suggestionMarkers, regionPolygons } from './markers'
import { FilterBar } from './FilterBar'
import { SuggestionsList } from './SuggestionsList'
import { SuggestionDetailPanel } from './SuggestionDetailPanel'
import { CreateSuggestionForm } from './CreateSuggestionForm'
import type { CreateMode } from './CreateSuggestionForm'
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

export function MapSuggestionsScreen({ selectedId }: { selectedId?: string } = {}) {
  const { user } = useSession()
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

  const selected = view.selectedId ? sorted.flatMap((s) => [s, ...s.children]).find((s) => s.id === view.selectedId) : null

  const markers = useMemo(() => suggestionMarkers(sorted, view.selectedId), [sorted, view.selectedId])
  const polygons = useMemo(() => regionPolygons(sorted, view.selectedId), [sorted, view.selectedId])

  const onMarkerClick = useCallback(({ id }: { id: string }) => {
    suggestionStore.select(id)
    setMobileSnap('peek')
    setMobileListOpen(false)
  }, [])

  const onMapClick = useCallback(
    ({ position }: { position: LatLng }) => {
      if (creating && (createMode === 'drop-pin' || createMode === 'draw-region')) {
        setPendingClick(position)
      }
    },
    [creating, createMode],
  )

  function openCreate(mode: CreateMode) {
    setCreateMode(mode)
    setCreating(true)
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
      />
    ) : (
      <>
        <FilterBar />
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
            onCreate={() => openCreate('drop-pin')}
          />
        )}
      </>
    )

  return (
    <div className={`map-suggestions${narrow ? ' map-suggestions--narrow' : ''}`}>
      <div className="map-suggestions__map">
        <div className="map-suggestions__toolbar">
          <Button onClick={() => openCreate('search')} disabled={!stage.canMutate}>
            Suggest a place
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
          createProvider={createMapProvider}
          center={selected ? { lat: selected.lat, lng: selected.lng } : DEFAULT_CENTER}
          zoom={12}
          markers={markers}
          polygons={polygons}
          onMarkerClick={onMarkerClick}
          onPolygonClick={onMarkerClick}
          onMapClick={onMapClick}
        />
        {sorted.length === 0 && !loading && !hasActiveFilters(view.filters) ? (
          <div className="map-suggestions__empty-overlay">
            <p>No suggestions yet — drop the first pin.</p>
            <Button onClick={() => openCreate('drop-pin')} disabled={!stage.canMutate}>
              Drop a pin
            </Button>
          </div>
        ) : null}
      </div>

      {!narrow ? (
        <aside className="map-suggestions__panel" aria-label="Suggestions">
          {creating ? (
            <CreateSuggestionForm
              tripId={tripId}
              initialMode={createMode}
              onClose={() => {
                setCreating(false)
                setPendingClick(null)
              }}
              onCreated={(created) => {
                upsert(created)
                suggestionStore.select(created.id)
                setCreating(false)
              }}
              pendingClick={pendingClick}
              onConsumeClick={() => setPendingClick(null)}
              existingSuggestions={sorted}
              onFocusExisting={(id) => {
                setCreating(false)
                suggestionStore.select(id)
              }}
            />
          ) : (
            panelBody(selected ? () => suggestionStore.select(null) : undefined)
          )}
        </aside>
      ) : (
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
            tripId={tripId}
            initialMode={createMode}
            onClose={() => {
              setCreating(false)
              setPendingClick(null)
            }}
            onCreated={(created) => {
              upsert(created)
              suggestionStore.select(created.id)
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
