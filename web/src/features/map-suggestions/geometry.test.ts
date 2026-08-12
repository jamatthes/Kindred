import { describe, expect, it } from 'vitest'
import { circleGeometry, geometryToPolygonSpec, haversineM, polygonGeometry, regionCentroid } from './geometry'

describe('regionCentroid', () => {
  it('returns the point itself for a circle', () => {
    const geometry = circleGeometry({ lat: 50.4, lng: -4.7 }, 12000)
    expect(regionCentroid(geometry)).toEqual({ lat: 50.4, lng: -4.7 })
  })

  it('averages the vertices for a polygon, respecting [lng, lat] GeoJSON order', () => {
    const geometry = polygonGeometry([
      { lat: 50.46, lng: -4.85 },
      { lat: 50.46, lng: -4.55 },
      { lat: 50.32, lng: -4.55 },
      { lat: 50.32, lng: -4.85 },
    ])
    const centroid = regionCentroid(geometry)
    expect(centroid.lat).toBeCloseTo(50.39, 2)
    expect(centroid.lng).toBeCloseTo(-4.7, 2)
  })

  it('does not double-count a ring whose first point already repeats as the last', () => {
    const geometry = polygonGeometry([
      { lat: 0, lng: 0 },
      { lat: 0, lng: 2 },
      { lat: 2, lng: 2 },
      { lat: 2, lng: 0 },
      { lat: 0, lng: 0 },
    ])
    expect(regionCentroid(geometry)).toEqual({ lat: 1, lng: 1 })
  })
})

describe('circleGeometry', () => {
  it('clamps radius to the sane maximum (200km)', () => {
    const geometry = circleGeometry({ lat: 0, lng: 0 }, 10_000_000)
    expect(geometry.properties.shape).toBe('circle')
    if (geometry.properties.shape === 'circle') expect(geometry.properties.radius_m).toBe(200_000)
  })
})

describe('geometryToPolygonSpec', () => {
  it('round-trips a polygon into map/types.ts PolygonSpec shape, closing the ring per the GeoJSON encoding', () => {
    const path = [
      { lat: 1, lng: 2 },
      { lat: 3, lng: 4 },
      { lat: 5, lng: 6 },
    ]
    const spec = geometryToPolygonSpec(polygonGeometry(path))
    expect(spec.shape).toBe('polygon')
    expect(spec.path).toEqual([...path, path[0]])
  })
})

describe('haversineM', () => {
  it('is zero for the same point and positive otherwise', () => {
    expect(haversineM({ lat: 50, lng: -4 }, { lat: 50, lng: -4 })).toBe(0)
    expect(haversineM({ lat: 50, lng: -4 }, { lat: 51, lng: -4 })).toBeGreaterThan(100_000)
  })
})
