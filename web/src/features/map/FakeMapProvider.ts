/**
 * FakeMapProvider — deterministic, DOM-based `MapProvider`.
 *
 * Used by every test in this feature and by the styleguide. It "honestly exercises the
 * interface" (per the pre-build brief): positions come from the real linear lat/lng
 * projection in `projection.ts`, and markers/polygons are real DOM nodes appended to the
 * container — not a mock that just records calls. It builds those nodes imperatively
 * (`document.createElement`), the same way a real map SDK's marker layer works, rather
 * than mounting React — `MapProvider` is deliberately framework-agnostic so a future
 * `GoogleMapProvider` (which also manages its own native DOM/canvas layer) fits the same
 * shape. It reuses the exact CSS classnames and icon markup the presentational
 * `SuggestionPin`/`RegionPolygon` components render, so the fake and the real JSX agree on
 * what a pin looks like.
 */

import { CATEGORY_ICON_PATHS, STATUS_GLYPH, suggestionPinClassName } from './SuggestionPin'
import { prefTintClass } from './prefTint'
import { notWiredYet, type MapProvider } from './MapProvider'
import { centroid, project, radiusInPixels } from './projection'
import type { Viewport } from './projection'
import type {
  Bounds,
  LatLng,
  MapEventHandler,
  MapEventMap,
  MapEventName,
  MapViewState,
  MarkerSpec,
  PolygonSpec,
} from './types'

const DEFAULT_WIDTH = 800
const DEFAULT_HEIGHT = 600
const MIN_ZOOM = 0
const MAX_ZOOM = 18

type MarkerEntry = { spec: MarkerSpec; el: HTMLElement }
type PolygonEntry = { spec: PolygonSpec; el: SVGGraphicsElement }

export class FakeMapProvider implements MapProvider {
  private container: HTMLElement | null = null
  private markersLayer: HTMLElement | null = null
  private svg: SVGSVGElement | null = null
  private viewport: Viewport = { center: { lat: 0, lng: 0 }, zoom: 2, width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT }
  private markers = new Map<string, MarkerEntry>()
  private polygons = new Map<string, PolygonEntry>()
  private listeners = new Map<MapEventName, Set<(payload: unknown) => void>>()

  mount(container: HTMLElement, initial: MapViewState): void {
    this.container = container
    container.innerHTML = ''
    container.classList.add('k-fake-map-surface')

    const width = container.clientWidth || DEFAULT_WIDTH
    const height = container.clientHeight || DEFAULT_HEIGHT
    this.viewport = { center: initial.center, zoom: initial.zoom, width, height }

    const svgNs = 'http://www.w3.org/2000/svg'
    this.svg = document.createElementNS(svgNs, 'svg') as SVGSVGElement
    this.svg.setAttribute('class', 'k-region-svg')
    this.svg.setAttribute('width', String(width))
    this.svg.setAttribute('height', String(height))
    this.svg.setAttribute('viewBox', `0 0 ${width} ${height}`)
    container.appendChild(this.svg)

    this.markersLayer = document.createElement('div')
    this.markersLayer.className = 'k-fake-map-markers'
    container.appendChild(this.markersLayer)

    container.addEventListener('click', this.handleSurfaceClick)
  }

  unmount(): void {
    this.container?.removeEventListener('click', this.handleSurfaceClick)
    if (this.container) this.container.innerHTML = ''
    this.container = null
    this.svg = null
    this.markersLayer = null
    this.markers.clear()
    this.polygons.clear()
    this.listeners.clear()
  }

  private handleSurfaceClick = (event: MouseEvent) => {
    // Only a click on bare surface (not a marker/polygon, which stop propagation
    // themselves) counts as a map click.
    if (event.target === this.container || event.target === this.svg || event.target === this.markersLayer) {
      const rect = this.container!.getBoundingClientRect()
      const point = { x: event.clientX - rect.left, y: event.clientY - rect.top }
      this.emit('mapClick', { position: this.toLatLng(point) })
    }
  }

  private toLatLng(point: { x: number; y: number }): LatLng {
    const scale = 2 ** this.viewport.zoom * 8
    return {
      lat: this.viewport.center.lat - (point.y - this.viewport.height / 2) / scale,
      lng: this.viewport.center.lng + (point.x - this.viewport.width / 2) / scale,
    }
  }

  setCenter(center: LatLng): void {
    this.viewport = { ...this.viewport, center }
    this.reprojectAll()
  }

  panTo(center: LatLng): void {
    // No animation in the fake — deterministic tests need no timers to flush.
    this.setCenter(center)
  }

  setZoom(zoom: number): void {
    this.viewport = { ...this.viewport, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)) }
    this.reprojectAll()
  }

  fitBounds(bounds: Bounds, _paddingPx = 0): void {
    const center = centroid([
      { lat: bounds.north, lng: bounds.east },
      { lat: bounds.south, lng: bounds.west },
    ])
    this.viewport = { ...this.viewport, center }
    this.reprojectAll()
  }

  getViewState(): MapViewState {
    return { center: this.viewport.center, zoom: this.viewport.zoom }
  }

  addMarker(spec: MarkerSpec): void {
    if (this.markers.has(spec.id)) {
      throw new Error(`FakeMapProvider.addMarker: marker "${spec.id}" already exists`)
    }
    const el = this.buildMarkerElement(spec)
    this.markersLayer?.appendChild(el)
    this.markers.set(spec.id, { spec, el })
  }

  updateMarker(spec: MarkerSpec): void {
    const existing = this.markers.get(spec.id)
    if (!existing) {
      throw new Error(`FakeMapProvider.updateMarker: marker "${spec.id}" does not exist`)
    }
    existing.el.remove()
    const el = this.buildMarkerElement(spec)
    this.markersLayer?.appendChild(el)
    this.markers.set(spec.id, { spec, el })
  }

  removeMarker(id: string): void {
    const existing = this.markers.get(id)
    if (!existing) return
    existing.el.remove()
    this.markers.delete(id)
  }

  addPolygon(spec: PolygonSpec): void {
    if (this.polygons.has(spec.id)) {
      throw new Error(`FakeMapProvider.addPolygon: polygon "${spec.id}" already exists`)
    }
    const el = this.buildPolygonElement(spec)
    this.svg?.appendChild(el)
    this.polygons.set(spec.id, { spec, el })
  }

  updatePolygon(spec: PolygonSpec): void {
    const existing = this.polygons.get(spec.id)
    if (!existing) {
      throw new Error(`FakeMapProvider.updatePolygon: polygon "${spec.id}" does not exist`)
    }
    existing.el.remove()
    const el = this.buildPolygonElement(spec)
    this.svg?.appendChild(el)
    this.polygons.set(spec.id, { spec, el })
  }

  removePolygon(id: string): void {
    const existing = this.polygons.get(id)
    if (!existing) return
    existing.el.remove()
    this.polygons.delete(id)
  }

  on<K extends MapEventName>(event: K, handler: MapEventHandler<K>): () => void {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set())
    const set = this.listeners.get(event)!
    set.add(handler as (payload: unknown) => void)
    return () => set.delete(handler as (payload: unknown) => void)
  }

  private emit<K extends MapEventName>(event: K, payload: MapEventMap[K]): void {
    this.listeners.get(event)?.forEach((handler) => handler(payload))
  }

  /** Test-only accessor: the current DOM node for a marker, so tests can assert on
   *  projected position/classes without reaching into private state. */
  getMarkerElement(id: string): HTMLElement | undefined {
    return this.markers.get(id)?.el
  }

  getPolygonElement(id: string): SVGGraphicsElement | undefined {
    return this.polygons.get(id)?.el
  }

  private reprojectAll(): void {
    for (const { spec, el } of this.markers.values()) {
      const point = project(spec.position, this.viewport)
      el.style.left = `${point.x}px`
      el.style.top = `${point.y}px`
    }
    for (const { spec } of this.polygons.values()) {
      // Rebuild — simplest correct approach; the fake favours correctness over the
      // micro-optimisation a real SDK would need.
      this.updatePolygon(spec)
    }
  }

  private buildMarkerElement(spec: MarkerSpec): HTMLElement {
    const point = project(spec.position, this.viewport)
    const el = document.createElement('button')
    el.type = 'button'
    el.style.position = 'absolute'
    el.style.left = `${point.x}px`
    el.style.top = `${point.y}px`
    el.style.transform = 'translate(-50%, -100%)'
    el.dataset.markerId = spec.id
    el.dataset.testid = spec.kind === 'suggestion' ? 'suggestion-pin' : 'live-marker'

    if (spec.kind === 'suggestion') {
      el.className = suggestionPinClassName(spec)
      el.style.background = spec.familyColor ?? 'var(--color-text-muted)'
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
      icon.setAttribute('class', 'k-pin__icon')
      icon.setAttribute('viewBox', '0 0 24 24')
      icon.setAttribute('fill', 'none')
      icon.setAttribute('stroke', 'currentColor')
      icon.innerHTML = CATEGORY_ICON_PATHS[spec.category]
      el.appendChild(icon)
      const glyph = STATUS_GLYPH[spec.status]
      if (glyph) {
        const badge = document.createElement('span')
        badge.className = 'k-pin__status-glyph'
        badge.textContent = glyph
        el.appendChild(badge)
      }
    } else {
      el.className = ['k-live-marker', spec.selected ? 'is-selected' : ''].filter(Boolean).join(' ')
      el.style.transform = 'translate(-50%, -50%)'
      const badge = document.createElement('span')
      badge.className = ['k-badge', 'k-badge--40', spec.online === false ? 'is-offline' : '']
        .filter(Boolean)
        .join(' ')
      badge.style.borderColor = spec.familyColor
      badge.title = spec.name
      const initials = document.createElement('span')
      initials.className = 'k-badge__initials'
      initials.textContent = spec.initials
      badge.appendChild(initials)
      el.appendChild(badge)
    }

    el.addEventListener('click', (event) => {
      event.stopPropagation()
      this.emit('markerClick', { id: spec.id })
    })
    el.addEventListener('mouseenter', () => this.emit('markerHover', { id: spec.id }))
    el.addEventListener('mouseleave', () => this.emit('markerHover', { id: null }))

    return el
  }

  private buildPolygonElement(spec: PolygonSpec): SVGGraphicsElement {
    const svgNs = 'http://www.w3.org/2000/svg'
    const tintClass = prefTintClass(spec.prefScore)
    const className = ['k-region', tintClass, spec.selected ? 'is-selected' : ''].filter(Boolean).join(' ')

    let el: SVGGraphicsElement
    if (spec.shape === 'circle' && spec.center && spec.radiusM !== undefined) {
      const center = project(spec.center, this.viewport)
      const radius = radiusInPixels(spec.radiusM, spec.center, this.viewport)
      el = document.createElementNS(svgNs, 'circle')
      el.setAttribute('cx', String(center.x))
      el.setAttribute('cy', String(center.y))
      el.setAttribute('r', String(radius))
    } else {
      const points = (spec.path ?? []).map((p) => project(p, this.viewport))
      const d =
        points.length === 0
          ? ''
          : `M ${points[0].x} ${points[0].y} ` +
            points
              .slice(1)
              .map((p) => `L ${p.x} ${p.y}`)
              .join(' ') +
            ' Z'
      el = document.createElementNS(svgNs, 'path')
      el.setAttribute('d', d)
    }

    el.setAttribute('class', className)
    el.dataset.testid = 'region-polygon'
    el.dataset.shape = spec.shape
    el.dataset.boundarySource = spec.boundarySource ?? 'drawn'
    if (spec.prefScore !== undefined && spec.prefScore !== null) {
      el.dataset.prefScore = String(spec.prefScore)
    }
    el.addEventListener('click', (event) => {
      event.stopPropagation()
      this.emit('polygonClick', { id: spec.id })
    })

    return el
  }
}

/** A `MapProvider` factory matching the shape `MapCanvas` expects, so swapping providers
 *  is a one-line change at the call site. */
export function createFakeMapProvider(): MapProvider {
  return new FakeMapProvider()
}

// Re-exported purely so callers importing `FakeMapProvider` don't also need to reach into
// `MapProvider.ts` just to construct the "not wired yet" error in their own tests/mocks.
export { notWiredYet }
