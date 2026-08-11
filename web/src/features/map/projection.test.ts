import { describe, expect, it } from 'vitest'
import { boundsOf, centroid, metersPerPixel, project, radiusInPixels, scaleForZoom, unproject } from './projection'
import type { Viewport } from './projection'

const viewport: Viewport = {
  center: { lat: 50.4, lng: -4.7 },
  zoom: 3,
  width: 800,
  height: 600,
}

describe('scaleForZoom', () => {
  it('doubles per zoom level from the base', () => {
    expect(scaleForZoom(1)).toBe(scaleForZoom(0) * 2)
    expect(scaleForZoom(2)).toBe(scaleForZoom(0) * 4)
  })
})

describe('project / unproject', () => {
  it('projects the viewport centre to the container centre', () => {
    const point = project(viewport.center, viewport)
    expect(point.x).toBeCloseTo(viewport.width / 2)
    expect(point.y).toBeCloseTo(viewport.height / 2)
  })

  it('moves north (higher lat) upward on screen (smaller y)', () => {
    const north = project({ lat: viewport.center.lat + 1, lng: viewport.center.lng }, viewport)
    expect(north.y).toBeLessThan(viewport.height / 2)
  })

  it('moves east (higher lng) rightward on screen (larger x)', () => {
    const east = project({ lat: viewport.center.lat, lng: viewport.center.lng + 1 }, viewport)
    expect(east.x).toBeGreaterThan(viewport.width / 2)
  })

  it('round-trips project → unproject for arbitrary points', () => {
    const positions = [
      { lat: 50.9, lng: -3.9 },
      { lat: 49.8, lng: -5.6 },
      viewport.center,
    ]
    for (const position of positions) {
      const point = project(position, viewport)
      const back = unproject(point, viewport)
      expect(back.lat).toBeCloseTo(position.lat, 9)
      expect(back.lng).toBeCloseTo(position.lng, 9)
    }
  })

  it('is a pure function of its inputs (deterministic, no hidden state)', () => {
    const a = project({ lat: 51, lng: -3 }, viewport)
    const b = project({ lat: 51, lng: -3 }, viewport)
    expect(a).toEqual(b)
  })
})

describe('metersPerPixel / radiusInPixels', () => {
  it('shrinks metres-per-pixel as zoom increases (more detail per pixel)', () => {
    const near = metersPerPixel(50, 3)
    const far = metersPerPixel(50, 5)
    expect(far).toBeLessThan(near)
  })

  it('scales the pixel radius linearly with the metre radius at a fixed zoom', () => {
    const small = radiusInPixels(1000, viewport.center, viewport)
    const big = radiusInPixels(2000, viewport.center, viewport)
    expect(big).toBeCloseTo(small * 2, 5)
  })

  it('returns a positive radius for a positive metre radius', () => {
    expect(radiusInPixels(5000, viewport.center, viewport)).toBeGreaterThan(0)
  })
})

describe('boundsOf', () => {
  it('returns null for an empty list', () => {
    expect(boundsOf([])).toBeNull()
  })

  it('computes the tight bounding box', () => {
    const bounds = boundsOf([
      { lat: 50, lng: -5 },
      { lat: 51, lng: -4 },
      { lat: 49.5, lng: -6 },
    ])
    expect(bounds).toEqual({ north: 51, south: 49.5, east: -4, west: -6 })
  })
})

describe('centroid', () => {
  it('averages a single point to itself', () => {
    expect(centroid([{ lat: 10, lng: 20 }])).toEqual({ lat: 10, lng: 20 })
  })

  it('is the vertex-average, not the bounding-box midpoint', () => {
    // Three points skewed toward the north-east corner: the vertex-average sits closer to
    // them than the bbox midpoint would, so this distinguishes the two algorithms.
    const points = [
      { lat: 0, lng: 0 },
      { lat: 9, lng: 9 },
      { lat: 9, lng: 9 },
    ]
    const c = centroid(points)
    expect(c.lat).toBeCloseTo(6)
    expect(c.lng).toBeCloseTo(6)
  })
})
