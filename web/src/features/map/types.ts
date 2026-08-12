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

/** `suggestions.type` per `plan/features/map-suggestions/design.md`. Drives pin icon and
 *  grouping; `region` is also the discriminator for polygon rendering. */
export type SuggestionCategory = 'accommodation' | 'activity' | 'meal' | 'region'

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
  mapClick: { position: LatLng }
}

export type MapEventName = keyof MapEventMap
export type MapEventHandler<K extends MapEventName> = (payload: MapEventMap[K]) => void
