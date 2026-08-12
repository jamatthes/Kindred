import { describe, expect, it } from 'vitest'
import { clusterSuggestions, regionPolygons, suggestionMarkers } from './markers'
import { circleGeometry } from './geometry'
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

describe('suggestionMarkers', () => {
  it('builds one marker per top-level, non-region suggestion, resolving family colour', () => {
    const markers = suggestionMarkers([suggestion()], null)
    expect(markers).toHaveLength(1)
    expect(markers[0]).toMatchObject({ id: 's1', kind: 'suggestion', category: 'accommodation', familyColor: 'var(--family-3)' })
  })

  it('excludes regions — they render as polygons, never pins', () => {
    const region = suggestion({ id: 'r1', type: 'region', geometry_geojson: circleGeometry({ lat: 50.4, lng: -4.7 }, 5000) })
    expect(suggestionMarkers([region], null)).toHaveLength(0)
  })

  it('marks the selected suggestion', () => {
    const markers = suggestionMarkers([suggestion({ id: 's1' }), suggestion({ id: 's2' })], 's2')
    expect(markers.find((m) => m.id === 's1')?.selected).toBeFalsy()
    expect(markers.find((m) => m.id === 's2')?.selected).toBe(true)
  })

  it('renders grouped children as their own offset markers, still individually clickable', () => {
    const parent = suggestion({
      id: 'accom',
      children: [
        suggestion({ id: 'meal-1', type: 'meal', lat: 50.4, lng: -4.7 }),
        suggestion({ id: 'meal-2', type: 'meal', lat: 50.4, lng: -4.7 }),
      ],
    })
    const markers = suggestionMarkers([parent], null)
    const ids = markers.map((m) => m.id)
    expect(ids).toEqual(expect.arrayContaining(['accom', 'meal-1', 'meal-2']))
    // Offset so they do not sit exactly on top of the parent or each other.
    const parentMarker = markers.find((m) => m.id === 'accom')!
    const child1 = markers.find((m) => m.id === 'meal-1')!
    const child2 = markers.find((m) => m.id === 'meal-2')!
    expect(child1.position).not.toEqual(parentMarker.position)
    expect(child1.position).not.toEqual(child2.position)
  })
})

describe('regionPolygons', () => {
  it('builds a polygon spec only for regions, carrying shape/centre/radius', () => {
    const region = suggestion({
      id: 'r1',
      type: 'region',
      geometry_geojson: circleGeometry({ lat: 50.4, lng: -4.7 }, 5000),
    })
    const polys = regionPolygons([suggestion(), region], null)
    expect(polys).toHaveLength(1)
    expect(polys[0]).toMatchObject({ id: 'r1', shape: 'circle', center: { lat: 50.4, lng: -4.7 }, radiusM: 5000 })
  })
})

describe('clusterSuggestions', () => {
  it('groups suggestions close together at a given zoom into one cluster', () => {
    const clusters = clusterSuggestions(
      [suggestion({ id: 'a', lat: 50.4, lng: -4.7 }), suggestion({ id: 'b', lat: 50.4001, lng: -4.7001 })],
      10,
    )
    expect(clusters).toHaveLength(1)
    expect(clusters[0].suggestionIds).toEqual(expect.arrayContaining(['a', 'b']))
  })

  it('does not cluster a single suggestion, or suggestions far apart', () => {
    expect(clusterSuggestions([suggestion({ id: 'a' })], 10)).toHaveLength(0)
    const far = clusterSuggestions(
      [suggestion({ id: 'a', lat: 50.4, lng: -4.7 }), suggestion({ id: 'b', lat: 10, lng: 10 })],
      10,
    )
    expect(far).toHaveLength(0)
  })

  it('never clusters regions', () => {
    const region = suggestion({ id: 'r1', type: 'region', geometry_geojson: circleGeometry({ lat: 50.4, lng: -4.7 }, 5000) })
    const clusters = clusterSuggestions([region, suggestion({ id: 'a' }), suggestion({ id: 'b', lat: 50.4001, lng: -4.7001 })], 10)
    expect(clusters.every((c) => !c.suggestionIds.includes('r1'))).toBe(true)
  })
})
