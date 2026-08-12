import { afterEach, describe, expect, it, vi } from 'vitest'
import { FakeMapProvider } from './FakeMapProvider'
import type { LiveMarkerSpec, PolygonSpec, SuggestionMarkerSpec } from './types'

function makeContainer(width = 800, height = 600): HTMLDivElement {
  const el = document.createElement('div')
  Object.defineProperty(el, 'clientWidth', { value: width, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: height, configurable: true })
  Object.defineProperty(el, 'getBoundingClientRect', {
    value: () => ({ left: 0, top: 0, right: width, bottom: height, width, height, x: 0, y: 0, toJSON() {} }),
    configurable: true,
  })
  document.body.appendChild(el)
  return el
}

const suggestion: SuggestionMarkerSpec = {
  id: 's1',
  kind: 'suggestion',
  position: { lat: 50.4, lng: -4.7 },
  category: 'meal',
  status: 'proposed',
  familyColor: 'var(--family-2)',
}

const live: LiveMarkerSpec = {
  id: 'u1',
  kind: 'live',
  position: { lat: 50.41, lng: -4.71 },
  familyColor: 'var(--family-4)',
  initials: 'TP',
  name: 'Tom P.',
  online: true,
}

const polygon: PolygonSpec = {
  id: 'r1',
  shape: 'polygon',
  path: [
    { lat: 50.5, lng: -4.9 },
    { lat: 50.5, lng: -4.5 },
    { lat: 50.3, lng: -4.5 },
  ],
  prefScore: 7,
}

describe('FakeMapProvider — provider interface conformance', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('mounts into a real DOM container', () => {
    const provider = new FakeMapProvider()
    const container = makeContainer()
    provider.mount(container, { center: { lat: 50.4, lng: -4.7 }, zoom: 3 })
    expect(container.querySelector('svg.k-region-svg')).toBeTruthy()
    expect(container.querySelector('.k-fake-map-markers')).toBeTruthy()
  })

  it('reports the mounted view state back', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: { lat: 1, lng: 2 }, zoom: 5 })
    expect(provider.getViewState()).toEqual({ center: { lat: 1, lng: 2 }, zoom: 5 })
  })

  it('unmount clears the container and is idempotent-safe to call once', () => {
    const provider = new FakeMapProvider()
    const container = makeContainer()
    provider.mount(container, { center: { lat: 0, lng: 0 }, zoom: 2 })
    provider.addMarker(suggestion)
    provider.unmount()
    expect(container.innerHTML).toBe('')
  })
})

describe('FakeMapProvider — marker lifecycle', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('adds a real DOM node for a suggestion marker, positioned by the linear projection', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(800, 600), { center: suggestion.position, zoom: 3 })
    provider.addMarker(suggestion)
    const el = provider.getMarkerElement('s1')!
    expect(el).toBeInstanceOf(HTMLElement)
    // Marker sits at the view centre, so it lands at the container's midpoint — computed
    // geometry, not a style decision, hence the token-check-ignore (400 = 800/2, 300 = 600/2).
    expect(el.style.left).toBe('400px') // token-check-ignore
    expect(el.style.top).toBe('300px') // token-check-ignore
  })

  it('throws when adding a marker id that already exists — callers diff, they do not guess', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: { lat: 0, lng: 0 }, zoom: 2 })
    provider.addMarker(suggestion)
    expect(() => provider.addMarker(suggestion)).toThrow(/already exists/)
  })

  it('updateMarker replaces the DOM node in place, reflecting new spec fields', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: { lat: 0, lng: 0 }, zoom: 2 })
    provider.addMarker(suggestion)
    provider.updateMarker({ ...suggestion, status: 'approved' })
    const el = provider.getMarkerElement('s1')!
    expect(el.className).toContain('k-pin--approved')
  })

  it('updateMarker throws for an id that was never added', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: { lat: 0, lng: 0 }, zoom: 2 })
    expect(() => provider.updateMarker(suggestion)).toThrow(/does not exist/)
  })

  it('removeMarker removes the node and is a no-op for an unknown id', () => {
    const provider = new FakeMapProvider()
    const container = makeContainer()
    provider.mount(container, { center: { lat: 0, lng: 0 }, zoom: 2 })
    provider.addMarker(suggestion)
    provider.removeMarker('s1')
    expect(provider.getMarkerElement('s1')).toBeUndefined()
    expect(() => provider.removeMarker('never-existed')).not.toThrow()
  })

  it('renders a live marker via the identity-badge classnames, family-coloured', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: live.position, zoom: 3 })
    provider.addMarker(live)
    const el = provider.getMarkerElement('u1')!
    expect(el.querySelector('.k-badge')).toBeTruthy()
    expect(el.querySelector('.k-badge__initials')?.textContent).toBe('TP')
  })

  it('re-projects every marker when the view centre changes', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(800, 600), { center: { lat: 0, lng: 0 }, zoom: 3 })
    provider.addMarker({ ...suggestion, position: { lat: 0, lng: 0 } })
    const before = provider.getMarkerElement('s1')!.style.left
    provider.setCenter({ lat: 0, lng: 5 })
    const after = provider.getMarkerElement('s1')!.style.left
    expect(after).not.toBe(before)
  })
})

describe('FakeMapProvider — polygon lifecycle', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('adds an SVG element tinted per the preference-ramp score', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: { lat: 50.4, lng: -4.7 }, zoom: 3 })
    provider.addPolygon(polygon)
    const el = provider.getPolygonElement('r1')!
    expect(el.getAttribute('class')).toContain('k-region--pref-7')
  })

  it('a circle region computes a positive pixel radius from radiusM', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: { lat: 50.4, lng: -4.7 }, zoom: 5 })
    provider.addPolygon({ id: 'c1', shape: 'circle', center: { lat: 50.4, lng: -4.7 }, radiusM: 5000 })
    const el = provider.getPolygonElement('c1')!
    expect(Number(el.getAttribute('r'))).toBeGreaterThan(0)
  })

  it('removePolygon is a no-op for an unknown id', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: { lat: 0, lng: 0 }, zoom: 2 })
    expect(() => provider.removePolygon('missing')).not.toThrow()
  })
})

describe('FakeMapProvider — events', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('emits markerClick with the marker id, and stops it from also firing mapClick', () => {
    const provider = new FakeMapProvider()
    const container = makeContainer()
    provider.mount(container, { center: suggestion.position, zoom: 3 })
    provider.addMarker(suggestion)

    const onMarkerClick = vi.fn()
    const onMapClick = vi.fn()
    provider.on('markerClick', onMarkerClick)
    provider.on('mapClick', onMapClick)

    provider.getMarkerElement('s1')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(onMarkerClick).toHaveBeenCalledWith({ id: 's1' })
    expect(onMapClick).not.toHaveBeenCalled()
  })

  it('emits polygonClick with the polygon id', () => {
    const provider = new FakeMapProvider()
    provider.mount(makeContainer(), { center: { lat: 50.4, lng: -4.7 }, zoom: 3 })
    provider.addPolygon(polygon)
    const onPolygonClick = vi.fn()
    provider.on('polygonClick', onPolygonClick)
    provider.getPolygonElement('r1')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(onPolygonClick).toHaveBeenCalledWith({ id: 'r1' })
  })

  it('an unsubscribe function stops further delivery', () => {
    const provider = new FakeMapProvider()
    const container = makeContainer()
    provider.mount(container, { center: suggestion.position, zoom: 3 })
    provider.addMarker(suggestion)
    const onMarkerClick = vi.fn()
    const off = provider.on('markerClick', onMarkerClick)
    off()
    provider.getMarkerElement('s1')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(onMarkerClick).not.toHaveBeenCalled()
  })
})
