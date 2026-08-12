/**
 * Suggestions → `MarkerSpec`/`PolygonSpec` (`features/map/types.ts`), plus the clustering
 * `design.md` > "Map layer specifics" asks for and the pre-built map shell deliberately
 * left out (its own docblock: "cluster composition logic ... is presentation logic over
 * real data the M3 screen owns, not a provider-shell concern").
 *
 * Clustering here is a coarse grid over raw lat/lng rather than true screen-pixel distance,
 * because `MapProvider` exposes no pixel-projection query for a mounted provider (only
 * `FakeMapProvider`'s test-only accessors do). A grid cell sized relative to zoom is a
 * reasonable approximation for "pins close enough to overlap"; a future provider extension
 * exposing `project()` could replace this with an exact pixel-distance clustering pass
 * without changing this function's signature. Regions never cluster (`design.md`).
 */

import type { LatLng, MarkerSpec, PolygonSpec, SuggestionMarkerSpec } from '../map/types'
import type { Suggestion } from '../../app/types'
import { familyColor } from '../../design/familyColor'
import { geometryToPolygonSpec, regionCentroid } from './geometry'

/** Grouped children render offset on a small radial arrangement around the parent
 * (`design.md`), so each stays independently clickable. */
const GROUP_OFFSET_DEG = 0.0006

function offsetForIndex(index: number, total: number): LatLng {
  if (total <= 1) return { lat: 0, lng: 0 }
  const angle = (2 * Math.PI * index) / total
  return { lat: Math.sin(angle) * GROUP_OFFSET_DEG, lng: Math.cos(angle) * GROUP_OFFSET_DEG }
}

function toSuggestionMarker(s: Suggestion, position: LatLng, selectedId: string | null): SuggestionMarkerSpec {
  return {
    id: s.id,
    kind: 'suggestion',
    position,
    category: s.type,
    status: s.status,
    familyColor: familyColor({ color: s.created_by.family_color, color_custom: s.created_by.family_color_custom ?? null }),
    selected: s.id === selectedId,
  }
}

/** Flattens top-level suggestions plus their (already server-grouped) `children` into one
 * marker list, offsetting children around their parent's point per `design.md`. Regions are
 * excluded — they render as polygons via `regionPolygons` instead. */
export function suggestionMarkers(suggestions: Suggestion[], selectedId: string | null): MarkerSpec[] {
  const markers: MarkerSpec[] = []
  for (const s of suggestions) {
    if (s.type !== 'region') markers.push(toSuggestionMarker(s, { lat: s.lat, lng: s.lng }, selectedId))
    const children = s.children ?? []
    children.forEach((child, index) => {
      if (child.type === 'region') return
      const offset = offsetForIndex(index, children.length)
      markers.push(
        toSuggestionMarker(child, { lat: child.lat + offset.lat, lng: child.lng + offset.lng }, selectedId),
      )
    })
  }
  return markers
}

export function regionPolygons(suggestions: Suggestion[], selectedId: string | null, prefScoreFor?: (id: string) => number | null | undefined): PolygonSpec[] {
  const polygons: PolygonSpec[] = []
  for (const s of suggestions) {
    if (s.type !== 'region' || !s.geometry_geojson) continue
    const spec = geometryToPolygonSpec(s.geometry_geojson)
    polygons.push({
      id: s.id,
      shape: spec.shape,
      path: spec.path,
      center: spec.center,
      radiusM: spec.radiusM,
      prefScore: prefScoreFor?.(s.id) ?? null,
      boundarySource: spec.boundarySource,
      selected: s.id === selectedId,
    })
  }
  return polygons
}

export type Cluster = { center: LatLng; suggestionIds: string[]; categories: Set<Suggestion['type']> }

/** Grid cell width in degrees, halving per zoom step from a 15-degree cell at zoom 0 — wide
 * enough at low zoom that a country's worth of pins cluster, narrow enough by street level
 * (~zoom 16) that individual pins on the same block stay separate. */
function cellSizeDeg(zoom: number): number {
  return 15 / 2 ** zoom
}

/** Groups non-region suggestions (regions never cluster) into grid cells. A cell holding
 * one suggestion is not a cluster — callers should render it as a plain pin. */
export function clusterSuggestions(suggestions: Suggestion[], zoom: number): Cluster[] {
  const cell = cellSizeDeg(zoom)
  const buckets = new Map<string, Suggestion[]>()
  for (const s of suggestions) {
    if (s.type === 'region') continue
    const key = `${Math.round(s.lat / cell)}:${Math.round(s.lng / cell)}`
    const bucket = buckets.get(key) ?? []
    bucket.push(s)
    buckets.set(key, bucket)
  }
  const clusters: Cluster[] = []
  for (const bucket of buckets.values()) {
    if (bucket.length < 2) continue
    const center = bucket.reduce(
      (acc, s) => ({ lat: acc.lat + s.lat / bucket.length, lng: acc.lng + s.lng / bucket.length }),
      { lat: 0, lng: 0 },
    )
    clusters.push({ center, suggestionIds: bucket.map((s) => s.id), categories: new Set(bucket.map((s) => s.type)) })
  }
  return clusters
}

export { regionCentroid }
