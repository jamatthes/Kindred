/**
 * Projection math for `FakeMapProvider`.
 *
 * A genuine map projects lat/lng through Web Mercator; the fake provider deliberately
 * does not — a simple linear transform (degrees → pixels, scaled by zoom) is honest about
 * what it is (a DOM stand-in for tests and the styleguide, not a basemap) and is exact and
 * trivially invertible, which matters for the round-trip tests below.
 *
 * `y` increases downward in screen space but latitude increases northward, so `lat` is
 * negated when going to pixels and negated back when coming from them.
 */

import type { LatLng } from './types'

/** Pixels per degree of longitude at zoom 0. Doubles per zoom level, same as a real slippy
 *  map's tile scale, so `zoom` behaves the way a caller expects. */
const BASE_PX_PER_DEGREE = 8

export function scaleForZoom(zoom: number): number {
  return BASE_PX_PER_DEGREE * 2 ** zoom
}

export type Viewport = {
  center: LatLng
  zoom: number
  width: number
  height: number
}

export type Point = { x: number; y: number }

/** Projects a geographic point to container-relative pixels for the given viewport. */
export function project(position: LatLng, viewport: Viewport): Point {
  const scale = scaleForZoom(viewport.zoom)
  return {
    x: viewport.width / 2 + (position.lng - viewport.center.lng) * scale,
    y: viewport.height / 2 - (position.lat - viewport.center.lat) * scale,
  }
}

/** Inverse of `project` — pixels back to a geographic point. */
export function unproject(point: Point, viewport: Viewport): LatLng {
  const scale = scaleForZoom(viewport.zoom)
  return {
    lng: viewport.center.lng + (point.x - viewport.width / 2) / scale,
    lat: viewport.center.lat - (point.y - viewport.height / 2) / scale,
  }
}

/** Metres per pixel at a given latitude and zoom — used to size a circle region in
 *  pixels. Approximate (flat-earth at the circle's own latitude), which is adequate for a
 *  DOM stand-in whose whole point is not to be a real basemap. */
export function metersPerPixel(latitude: number, zoom: number): number {
  const EARTH_CIRCUMFERENCE_M = 40_075_016.686
  const metersPerDegreeLng = (EARTH_CIRCUMFERENCE_M * Math.cos((latitude * Math.PI) / 180)) / 360
  return metersPerDegreeLng / scaleForZoom(zoom)
}

/** Pixel radius for a circle of `radiusM` metres centred at `center`, at the given viewport. */
export function radiusInPixels(radiusM: number, center: LatLng, viewport: Viewport): number {
  const mpp = metersPerPixel(center.lat, viewport.zoom)
  if (mpp <= 0) return 0
  return radiusM / mpp
}

/** The smallest `Bounds` containing every position, or `null` for an empty list. */
export function boundsOf(positions: LatLng[]): { north: number; south: number; east: number; west: number } | null {
  if (positions.length === 0) return null
  let north = -Infinity
  let south = Infinity
  let east = -Infinity
  let west = Infinity
  for (const p of positions) {
    north = Math.max(north, p.lat)
    south = Math.min(south, p.lat)
    east = Math.max(east, p.lng)
    west = Math.min(west, p.lng)
  }
  return { north, south, east, west }
}

/** Centroid of a set of positions — used by `FakeMapProvider.fitBounds` to pick a centre;
 *  vertex-average, matching the region centroid rule in the map-suggestions design doc
 *  ("the polygon's vertex-average") rather than the bounds midpoint. */
export function centroid(positions: LatLng[]): LatLng {
  const sum = positions.reduce(
    (acc, p) => ({ lat: acc.lat + p.lat, lng: acc.lng + p.lng }),
    { lat: 0, lng: 0 },
  )
  return { lat: sum.lat / positions.length, lng: sum.lng / positions.length }
}
