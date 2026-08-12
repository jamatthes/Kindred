/**
 * The one place `suggestions.geometry_geojson`'s `[lng, lat]` GeoJSON order is converted to
 * and from our internal `LatLng` (`web/src/features/map/types.ts`). `design.md` > "Region
 * geometry encoding" is explicit that the conversion happens once — nothing else in the
 * codebase may reorder coordinates.
 */

import type { LatLng } from '../map/types'
import type { RegionGeometry } from '../../app/types'

const MAX_RADIUS_M = 200_000

/** A region's centroid, matching `Suggestion.centroid()` on the server
 * (`server/app/models/suggestion.py`): a circle's own point, or the vertex average of a
 * polygon ring (first/last point not double-counted). Pure, no I/O — mirrors the server so
 * the drawn shape and its stored `lat`/`lng` never disagree client-side either. */
export function regionCentroid(geometry: RegionGeometry): LatLng {
  if (geometry.geometry.type === 'Point') {
    const [lng, lat] = geometry.geometry.coordinates
    return { lat, lng }
  }
  const ring = geometry.geometry.coordinates[0] ?? []
  const points = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
    ? ring.slice(0, -1)
    : ring
  if (points.length === 0) return { lat: 0, lng: 0 }
  const sum = points.reduce((acc, [lng, lat]) => ({ lat: acc.lat + lat, lng: acc.lng + lng }), { lat: 0, lng: 0 })
  return { lat: sum.lat / points.length, lng: sum.lng / points.length }
}

/** Builds the circle encoding from `design.md`. `radiusM` is clamped to the server's sane
 * maximum so a runaway drag never produces a whole-globe circle client-side either. */
export function circleGeometry(center: LatLng, radiusM: number): RegionGeometry {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [center.lng, center.lat] },
    properties: { shape: 'circle', radius_m: Math.min(Math.max(radiusM, 1), MAX_RADIUS_M) },
  }
}

/** Builds the polygon encoding. `path` need not be closed — GeoJSON requires the ring to
 * repeat its first point, so this closes it if the caller did not. */
export function polygonGeometry(path: LatLng[]): RegionGeometry {
  const ring = path.map((p) => [p.lng, p.lat] as [number, number])
  const first = ring[0]
  const last = ring[ring.length - 1]
  const closed = first && last && first[0] === last[0] && first[1] === last[1] ? ring : [...ring, first]
  return {
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [closed] },
    properties: { shape: 'polygon' },
  }
}

/** The region's own shape/path/center/radius, in our `LatLng` — what `RegionPolygon` and
 * `PolygonSpec` (`features/map/types.ts`) need to render it. */
export function geometryToPolygonSpec(geometry: RegionGeometry): {
  shape: 'circle' | 'polygon'
  path?: LatLng[]
  center?: LatLng
  radiusM?: number
  boundarySource?: 'osm' | 'drawn'
} {
  if (geometry.properties.shape === 'circle') {
    const [lng, lat] = geometry.geometry.coordinates as [number, number]
    return { shape: 'circle', center: { lat, lng }, radiusM: geometry.properties.radius_m, boundarySource: geometry.properties.boundary_source }
  }
  const ring = (geometry.geometry.coordinates as [number, number][][])[0] ?? []
  const path = ring.map(([lng, lat]) => ({ lat, lng }))
  return { shape: 'polygon', path, boundarySource: geometry.properties.boundary_source }
}

/** Haversine distance in metres — used client-side only for the radius-by-two-clicks draw
 * tool (`CreateSuggestionForm`); the server is authoritative for everything persisted. */
export function haversineM(a: LatLng, b: LatLng): number {
  const R = 6_371_000
  const toRad = (deg: number) => (deg * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const lat1 = toRad(a.lat)
  const lat2 = toRad(b.lat)
  const sinDLat = Math.sin(dLat / 2)
  const sinDLng = Math.sin(dLng / 2)
  const h = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)))
}
