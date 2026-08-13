/**
 * Provider-agnostic map types — shared by `MapProvider`, `MapCanvas`, and every pin/
 * polygon component in this feature.
 *
 * Coordinates are always `{ lat, lng }` (our internal convention, matching
 * `suggestions.lat`/`lng` in `plan/architecture.md`), never `[lng, lat]` GeoJSON order.
 * `plan/features/map-suggestions/design.md` puts the one conversion at the API boundary;
 * everything under `features/map/` speaks `LatLng` exclusively.
 */

export type LatLng = { lat: number; lng: number }

export type Bounds = { north: number; south: number; east: number; west: number }

export type MapViewState = { center: LatLng; zoom: number }

/**
 * What `mount` needs beyond the view: the base map's colour scheme, so Google's tiles match
 * the app's theme instead of shining white through a dark UI.
 *
 * Mount-time only, deliberately. Google's `colorScheme` is fixed when the `Map` is
 * constructed and has no setter, so a live theme switch cannot be pushed into an existing
 * instance — `MapCanvas` is keyed on the resolved theme instead, and a change remounts the
 * provider and replays every marker. Modelling it as a mount option rather than a
 * `setColorScheme()` the SDK cannot honour keeps the interface honest about that.
 */
export type MapMountOptions = MapViewState & { colorScheme?: 'light' | 'dark' }

/** `suggestions.type` per `plan/features/map-suggestions/design.md`. Drives pin icon and
 *  grouping; `region` is also the discriminator for polygon rendering. */
export type SuggestionCategory = 'accommodation' | 'activity' | 'meal' | 'region' | 'other'

/** `suggestions.status`. Never carried by colour alone — see `MapPin`. */
export type SuggestionStatus = 'proposed' | 'shortlisted' | 'approved' | 'rejected' | 'scheduled'

/** A single suggestion pin: type icon + per-family colour accent + status treatment. */
export type SuggestionMarkerSpec = {
  id: string
  kind: 'suggestion'
  position: LatLng
  category: SuggestionCategory
  status: SuggestionStatus
  /** Resolved CSS colour from `design/familyColor.ts` — `var(--family-N)` or a custom hex.
      Resolved by the caller, not here: a slot number can no longer represent every family
      (overflow families carry a custom colour). Absent for a suggestion with no author
      family yet. */
  familyColor?: string | null
  selected?: boolean
}

/** A live-location / check-in pin, family-coloured, carrying a person's initials. */
export type LiveMarkerSpec = {
  id: string
  kind: 'live'
  position: LatLng
  /** Resolved CSS colour (see `SuggestionMarkerSpec.familyColor`), required — a live
      marker always belongs to a family. */
  familyColor: string
  initials: string
  /** Always supplied: the ring/colour is never the only identifier (design-system rule). */
  name: string
  online?: boolean
  selected?: boolean
}

export type MarkerSpec = SuggestionMarkerSpec | LiveMarkerSpec

/**
 * A region: circle or polygon, per the geometry encoding in
 * `plan/features/map-suggestions/design.md`. Both render identically — dashed outline,
 * tinted fill — the shape only changes how the outline is computed.
 */
export type PolygonSpec = {
  id: string
  shape: 'polygon' | 'circle'
  /** Required when `shape === 'polygon'`: closed or open ring, `[lng,lat]`-free (our
   *  `LatLng` order) — the last point need not repeat the first. */
  path?: LatLng[]
  /** Required when `shape === 'circle'`. */
  center?: LatLng
  radiusM?: number
  /** 0–10 preference score. Absent/null renders the neutral (non-scored) tint. */
  prefScore?: number | null
  /** ODbL requires attribution wherever a named-locality (OSM) boundary renders. */
  boundarySource?: 'osm' | 'drawn'
  selected?: boolean
}

export type MapEventMap = {
  markerClick: { id: string }
  markerHover: { id: string | null }
  polygonClick: { id: string }
  /** `placeId` is present when the click landed on one of the base map's own labelled places
   *  (Google calls this an `IconMouseEvent`). The provider suppresses the SDK's built-in info
   *  window for those clicks and hands the id up instead, because that window is Google-
   *  rendered chrome with no injection point for our "Add as suggestion" action — see
   *  `plan/features/map-suggestions/design.md` > "Map-first interaction model". A plain click
   *  on bare map has no `placeId`, which is exactly how a caller tells the two apart. */
  mapClick: { position: LatLng; placeId?: string }
  /** Right-click (long-press on touch). Opens the map's own context menu — "Drop a pin here"
   *  / "Draw a region here" — at the clicked point. */
  mapContextMenu: { position: LatLng }
  /** The view moved: pan, zoom, or a programmatic recentre. Anything drawn *over* the map in
   *  React rather than by the SDK has to re-project itself when this fires, or it slides off
   *  the thing it is pointing at the moment the user drags. */
  viewChange: MapViewState
}

export type MapEventName = keyof MapEventMap
export type MapEventHandler<K extends MapEventName> = (payload: MapEventMap[K]) => void
