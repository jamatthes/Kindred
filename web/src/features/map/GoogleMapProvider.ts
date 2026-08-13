/**
 * GoogleMapProvider — the real Google Maps JS integration.
 *
 * Replaces the stub per this feature's own instruction in `plan/features/map-suggestions/
 * design.md`: "The M3 implementer's job is to replace this one file with the real Google
 * Maps JS integration ... nothing else in the feature should need to change." Every other
 * component in `features/map/` only ever talks to `MapProvider`, so this file is the entire
 * diff needed to go live once a browser key exists.
 *
 * **Not exercised by this phase's test suite or dev environment**: `plan/architecture.md`'s
 * Google API cost rules require a browser-restricted key that is not configured yet (same
 * caveat the stub's docblock carried), so `MapSuggestionsScreen` only constructs this class
 * when `VITE_GOOGLE_MAPS_BROWSER_KEY` is set — everywhere else (dev without a key, every
 * Vitest run) still gets `FakeMapProvider`. This class is therefore unverified against a
 * live key; it is straightforward Maps JS usage, but flag it for a manual smoke pass once a
 * key is provisioned (`plan/features/map-suggestions/tasks.md` Phase 12's Cloud Console
 * checklist covers provisioning it).
 */

import { notWiredYet, type MapProvider } from './MapProvider'
import { CATEGORY_ICON_PATHS, STATUS_GLYPH } from './SuggestionPin'
import type {
  Bounds,
  LatLng,
  MapEventHandler,
  MapEventMap,
  MapEventName,
  MapMountOptions,
  MapViewState,
  MarkerSpec,
  PolygonSpec,
} from './types'

const NAME = 'GoogleMapProvider'

type GoogleNamespace = typeof globalThis & { google?: { maps: GoogleMapsApi } }

// A pared-down structural type for the parts of the Maps JS API this file uses — not the
// full `@types/google.maps` surface, so this file adds no dependency (per `design.md`'s
// pre-build note: "no script tag, no dependency added").
type GoogleMapsApi = {
  Map: new (el: HTMLElement, opts: Record<string, unknown>) => GoogleMap
  Marker: new (opts: Record<string, unknown>) => GoogleMarker
  Circle: new (opts: Record<string, unknown>) => GoogleCircle
  Polygon: new (opts: Record<string, unknown>) => GooglePolygon
  Polyline: new (opts: Record<string, unknown>) => GooglePolyline
  SymbolPath: { CIRCLE: unknown }
  LatLngBounds: new () => { extend(pos: LatLng): void }
  LatLng: new (lat: number, lng: number) => unknown
  /** Constructed bare and given no-op lifecycle methods — an `OverlayView` attached to the
   *  map is the documented way to reach `MapCanvasProjection`, which is the only public API
   *  that converts a LatLng to container pixels. It draws nothing. */
  OverlayView: new () => GoogleOverlayView
  event: { clearInstanceListeners(instance: unknown): void }
}
type GoogleOverlayView = {
  onAdd?: () => void
  draw?: () => void
  onRemove?: () => void
  setMap(map: GoogleMap | null): void
  getProjection(): { fromLatLngToContainerPixel(latLng: unknown): { x: number; y: number } | null } | null
}
type GoogleMap = {
  setCenter(pos: LatLng): void
  panTo(pos: LatLng): void
  setZoom(zoom: number): void
  getZoom(): number
  getCenter(): { lat(): number; lng(): number }
  fitBounds(bounds: unknown, padding?: number): void
  addListener(event: string, handler: (e: GoogleMapMouseEvent) => void): { remove(): void }
}
/** Google fires `click` with a plain `MapMouseEvent` on bare map and an `IconMouseEvent` —
 *  same shape plus `placeId` and a `stop()` that cancels the SDK's own info window — when the
 *  click landed on one of the base map's labelled places. One handler, two arrivals. */
type GoogleMapMouseEvent = {
  latLng?: { lat(): number; lng(): number }
  placeId?: string
  stop?: () => void
}
type GoogleMarker = {
  setMap(map: GoogleMap | null): void
  setIcon(icon: unknown): void
  setTitle(title: string): void
  addListener(event: string, handler: () => void): { remove(): void }
}
type GoogleCircle = {
  setMap(map: GoogleMap | null): void
  setOptions(opts: Record<string, unknown>): void
  addListener(event: string, handler: () => void): { remove(): void }
}
type GooglePolygon = {
  setMap(map: GoogleMap | null): void
  setOptions(opts: Record<string, unknown>): void
  addListener(event: string, handler: () => void): { remove(): void }
}
type GooglePolyline = GooglePolygon

let loaderPromise: Promise<GoogleMapsApi> | null = null

/** Loads the Maps JS SDK exactly once per page, script-tag style — the same mechanism
 * every non-React Google Maps integration uses, and the one `design.md`'s pre-build note
 * says this file alone is responsible for adding. */
function loadGoogleMaps(apiKey: string): Promise<GoogleMapsApi> {
  const existing = (globalThis as GoogleNamespace).google?.maps
  if (existing) return Promise.resolve(existing)
  if (loaderPromise) return loaderPromise

  loaderPromise = new Promise((resolve, reject) => {
    const callbackName = '__kindredGoogleMapsReady'
    ;(window as unknown as Record<string, () => void>)[callbackName] = () => {
      const maps = (globalThis as GoogleNamespace).google?.maps
      if (maps) resolve(maps)
      else reject(new Error('Google Maps failed to initialise.'))
    }
    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=places&callback=${callbackName}`
    script.async = true
    script.onerror = () => reject(new Error('Google Maps script failed to load.'))
    document.head.appendChild(script)
  })
  return loaderPromise
}

/** `btoa` only accepts Latin-1 (code points 0x00-0xFF) and throws `InvalidCharacterError`
 * on anything past it — which every non-empty `STATUS_GLYPH` value is ('★'/'✓'/'✕'/'▸', all
 * well past 0xFF). Found by the M3 integration pass's live Playwright smoke as a real,
 * reproducible crash: approve (or shortlist/reject/schedule) a single suggestion, and every
 * later page load that renders its marker throws here — GoogleMapProvider never finishes
 * initialising, and with no `ErrorBoundary` anywhere in the app, the whole page goes blank.
 * The classic escape-hatch (encode to UTF-8 bytes first, then treat *those* bytes as
 * Latin-1) is the smallest fix that keeps `btoa` itself in the loop. */
export function toBase64Utf8(str: string): string {
  return btoa(unescape(encodeURIComponent(str)))
}

/** Builds a small SVG data-URL icon reusing the exact category/glyph vocabulary
 * `SuggestionPin` renders, so a Google marker and the fake/test marker agree on what a pin
 * looks like (same principle `FakeMapProvider` follows). */
function suggestionIcon(spec: Extract<MarkerSpec, { kind: 'suggestion' }>): { url: string; scaledSize: unknown } {
  // No family yet: the same muted token `SuggestionPin.tsx` falls back to, resolved from
  // the live stylesheet rather than a hardcoded hex (token-only styling applies to the
  // SDK's own colour options too — see `regionStyle` below for the same pattern).
  const color =
    spec.familyColor ?? getComputedStyle(document.documentElement).getPropertyValue('--color-text-muted').trim()
  const glyph = STATUS_GLYPH[spec.status] ?? ''
  const path = CATEGORY_ICON_PATHS[spec.category]
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24">
    <circle cx="12" cy="12" r="11" fill="${color}" stroke="white" stroke-width="1.5" />
    <g fill="none" stroke="white" stroke-width="2">${path}</g>
    ${glyph ? `<text x="19" y="6" font-size="8" fill="white">${glyph}</text>` : ''}
  </svg>`
  const url = `data:image/svg+xml;base64,${toBase64Utf8(svg)}`
  // `scaledSize` needs a live `google.maps.Size`; constructed lazily by the caller, which
  // has the loaded namespace in scope. This function only builds the icon URL.
  return { url, scaledSize: null }
}

export class GoogleMapProvider implements MapProvider {
  private maps: GoogleMapsApi | null = null
  private map: GoogleMap | null = null
  private markers = new Map<string, GoogleMarker>()
  /** A circle is one object; a polygon is a fill plus its dashed outline (see `addPolygon`). */
  private shapes = new Map<string, GoogleCircle | DashedRegion>()
  private listeners = new Map<MapEventName, Set<(payload: unknown) => void>>()
  private mapListeners: { remove(): void }[] = []
  private overlay: GoogleOverlayView | null = null
  // `mount` looks synchronous to `MapCanvas` (it never awaits it — see the comment there)
  // but the Maps JS script load behind it is not: `MapCanvas`'s own effects can call
  // `addMarker`/`addPolygon`/`setCenter` etc. before `this.map` exists, most obviously for
  // every suggestion already in the list when a screen first mounts. Every mutating method
  // below routes through `whenReady` so those calls queue and replay in order once the
  // script loads, instead of silently no-op'ing and permanently dropping that marker (the
  // bug this queue replaces: `addMarker` returning early when `this.map` was still null).
  private ready = false
  private queue: (() => void)[] = []
  private viewFrame: number | null = null

  /**
   * Emits `viewChange` once per animation frame until the map goes `idle`.
   *
   * Google's events are not a smooth stream. `bounds_changed` fires densely while a finger or
   * mouse is actually dragging, but the **inertial glide after release** is animated inside
   * the SDK and reports almost nothing until it stops — so an anchored card tracked the map
   * perfectly while dragging and then sat frozen mid-air as the map coasted out from under
   * it, snapping into place only on the next interaction. Exactly the bug you would expect
   * from trusting an event to mean "the view is moving now".
   *
   * A frame loop asks the question the events were being used to answer — where is the view
   * *now* — and `idle` is the one event that reliably says the movement is over. Nothing is
   * emitted between movements, so this costs nothing at rest.
   */
  private startViewTracking(): void {
    if (this.viewFrame !== null) return
    const tick = () => {
      if (!this.map) {
        this.viewFrame = null
        return
      }
      this.emit('viewChange', this.getViewState())
      this.viewFrame = requestAnimationFrame(tick)
    }
    this.viewFrame = requestAnimationFrame(tick)
  }

  private stopViewTracking(): void {
    if (this.viewFrame !== null) {
      cancelAnimationFrame(this.viewFrame)
      this.viewFrame = null
    }
    // One last emit so the resting position is exact rather than whatever the final frame
    // happened to catch mid-glide.
    if (this.map) this.emit('viewChange', this.getViewState())
  }

  private whenReady(fn: () => void): void {
    if (this.ready) fn()
    else this.queue.push(fn)
  }

  mount(container: HTMLElement, initial: MapMountOptions): void {
    const apiKey = (import.meta as unknown as { env?: Record<string, string> }).env
      ?.VITE_GOOGLE_MAPS_BROWSER_KEY
    if (!apiKey) throw notWiredYet(NAME, 'mount (no VITE_GOOGLE_MAPS_BROWSER_KEY configured)')

    // Synchronous-looking mount, asynchronous underneath: `MapCanvas` calls `mount` once
    // and never awaits it, so every subsequent call queues behind the load promise (via
    // `whenReady` above).
    loadGoogleMaps(apiKey)
      .then((maps) => {
        this.maps = maps
        this.map = new maps.Map(container, {
          center: initial.center,
          zoom: initial.zoom,
          disableDefaultUI: false,
          // Google's own light/dark tiles, chosen to match the app's resolved theme. The
          // string values are what `google.maps.ColorScheme` resolves to, passed literally so
          // this file still needs no `@types/google.maps` and no namespace read before the
          // SDK has finished loading. Construction-time only — see `MapMountOptions`.
          ...(initial.colorScheme ? { colorScheme: initial.colorScheme.toUpperCase() } : {}),
        })
        this.mapListeners.push(
          this.map.addListener('click', (e) => {
            if (!e.latLng) return
            // A POI click: cancel Google's own info window before it opens. We replace that
            // window with our own card (it is the only way to offer "Add as suggestion" —
            // the SDK's window takes no custom content), so letting both appear would be two
            // cards for one click.
            if (e.placeId) e.stop?.()
            this.emit('mapClick', {
              position: { lat: e.latLng.lat(), lng: e.latLng.lng() },
              ...(e.placeId ? { placeId: e.placeId } : {}),
            })
          }),
          this.map.addListener('rightclick', (e) => {
            if (!e.latLng) return
            this.emit('mapContextMenu', { position: { lat: e.latLng.lat(), lng: e.latLng.lng() } })
          }),
          // Any movement starts a per-frame tracking loop; `idle` ends it. See
          // `startViewTracking` for why the events alone are not enough.
          this.map.addListener('bounds_changed', () => this.startViewTracking()),
          this.map.addListener('dragend', () => this.startViewTracking()),
          this.map.addListener('zoom_changed', () => this.startViewTracking()),
          this.map.addListener('idle', () => this.stopViewTracking()),
        )

        // The projection carrier. `OverlayView` is abstract in name only — the SDK calls
        // these three hooks, so they must exist even though this overlay renders nothing.
        const overlay = new maps.OverlayView()
        overlay.onAdd = () => {}
        overlay.draw = () => {}
        overlay.onRemove = () => {}
        overlay.setMap(this.map)
        this.overlay = overlay
        this.ready = true
        const pending = this.queue
        this.queue = []
        for (const fn of pending) fn()
      })
      .catch((cause) => {
        // No UI fallback wired for a load failure *after* mount (a missing key is caught
        // synchronously above and `MapSuggestionsScreen` never constructs this class in
        // that case; this branch is a script/network failure with a key present, e.g. an
        // outage or an ad-blocker). Logged rather than left as an unhandled rejection, per
        // `design.md`'s edge case ("Map area shows an explanatory empty state") — the
        // container simply stays blank; wiring an error state through `MapProvider` for
        // this is a real follow-up, not something to grow inline here.
        // eslint-disable-next-line no-console
        console.error(`[${NAME}] failed to load Google Maps:`, cause)
      })
  }

  unmount(): void {
    this.stopViewTracking()
    for (const l of this.mapListeners) l.remove()
    this.mapListeners = []
    this.overlay?.setMap(null)
    this.overlay = null
    for (const marker of this.markers.values()) marker.setMap(null)
    for (const shape of this.shapes.values()) forEachShape(shape, (part) => part.setMap(null))
    this.markers.clear()
    this.shapes.clear()
    this.listeners.clear()
    this.map = null
    this.maps = null
    this.ready = false
    this.queue = []
  }

  setCenter(center: LatLng): void {
    this.whenReady(() => this.map?.setCenter(center))
  }
  panTo(center: LatLng): void {
    this.whenReady(() => this.map?.panTo(center))
  }
  setZoom(zoom: number): void {
    this.whenReady(() => this.map?.setZoom(zoom))
  }
  fitBounds(bounds: Bounds, paddingPx = 0): void {
    this.whenReady(() => {
      if (!this.map || !this.maps) return
      const b = new this.maps.LatLngBounds()
      b.extend({ lat: bounds.north, lng: bounds.east })
      b.extend({ lat: bounds.south, lng: bounds.west })
      this.map.fitBounds(b, paddingPx)
    })
  }
  getViewState(): MapViewState {
    if (!this.map) return { center: { lat: 0, lng: 0 }, zoom: 0 }
    const c = this.map.getCenter()
    return { center: { lat: c.lat(), lng: c.lng() }, zoom: this.map.getZoom() }
  }

  projectToContainerPoint(position: LatLng): { x: number; y: number } | null {
    // Null until the overlay has been added *and* the map has drawn once — asking earlier is
    // normal (a card can open on the same tick the map mounts), and guessing a point would
    // put the card somewhere confidently wrong.
    const projection = this.overlay?.getProjection()
    if (!projection || !this.maps) return null
    return projection.fromLatLngToContainerPixel(new this.maps.LatLng(position.lat, position.lng))
  }

  addMarker(spec: MarkerSpec): void {
    if (this.markers.has(spec.id)) throw new Error(`${NAME}.addMarker: marker "${spec.id}" already exists`)
    this.whenReady(() => {
      if (!this.map || !this.maps) return
      const marker = new this.maps.Marker({
        position: spec.position,
        map: this.map,
        title: spec.kind === 'live' ? spec.name : undefined,
        icon: spec.kind === 'suggestion' ? suggestionIcon(spec).url : undefined,
      })
      marker.addListener('click', () => this.emit('markerClick', { id: spec.id }))
      marker.addListener('mouseover', () => this.emit('markerHover', { id: spec.id }))
      marker.addListener('mouseout', () => this.emit('markerHover', { id: null }))
      this.markers.set(spec.id, marker)
    })
  }
  updateMarker(spec: MarkerSpec): void {
    this.whenReady(() => {
      const marker = this.markers.get(spec.id)
      if (!marker) throw new Error(`${NAME}.updateMarker: marker "${spec.id}" does not exist`)
      if (spec.kind === 'suggestion') marker.setIcon(suggestionIcon(spec).url)
      if (spec.kind === 'live') marker.setTitle(spec.name)
    })
  }
  removeMarker(id: string): void {
    this.whenReady(() => {
      const marker = this.markers.get(id)
      if (!marker) return
      marker.setMap(null)
      this.markers.delete(id)
    })
  }

  addPolygon(spec: PolygonSpec): void {
    if (this.shapes.has(spec.id)) throw new Error(`${NAME}.addPolygon: polygon "${spec.id}" already exists`)
    this.whenReady(() => {
      if (!this.map || !this.maps) return
      if (spec.shape === 'circle' && spec.center && spec.radiusM !== undefined) {
        const circle = new this.maps.Circle({
          center: spec.center,
          radius: spec.radiusM,
          map: this.map,
          ...regionStyle(spec),
        })
        circle.addListener('click', () => this.emit('polygonClick', { id: spec.id }))
        this.shapes.set(spec.id, circle)
        return
      }

      // Dashed outline + tinted fill (`design.md` > "Map layer specifics"). Google's
      // `Polygon` has no dash option at all — dashes exist only as repeated `icons` on a
      // `Polyline` — so the region is drawn as two overlapping objects: the polygon carries
      // the fill with its stroke switched off, and a closed polyline retraces the same ring
      // as dots. Both are registered under one id so add/update/remove stay one call each to
      // `MapCanvas`, which knows nothing of this split.
      const style = regionStyle(spec)
      const polygon = new this.maps.Polygon({
        paths: spec.path ?? [],
        map: this.map,
        ...style,
        strokeOpacity: 0,
        strokeWeight: 0,
      })
      const outline = new this.maps.Polyline({
        path: closedRing(spec.path ?? []),
        map: this.map,
        ...dashedStroke(style, spec.selected),
      })
      polygon.addListener('click', () => this.emit('polygonClick', { id: spec.id }))
      outline.addListener('click', () => this.emit('polygonClick', { id: spec.id }))
      this.shapes.set(spec.id, { fill: polygon, outline })
    })
  }
  updatePolygon(spec: PolygonSpec): void {
    this.whenReady(() => {
      const shape = this.shapes.get(spec.id)
      if (!shape) throw new Error(`${NAME}.updatePolygon: polygon "${spec.id}" does not exist`)
      const style = regionStyle(spec)
      if ('fill' in shape) {
        shape.fill.setOptions({ ...style, strokeOpacity: 0, strokeWeight: 0 })
        shape.outline.setOptions({ ...dashedStroke(style, spec.selected), path: closedRing(spec.path ?? []) })
        return
      }
      shape.setOptions(style)
    })
  }
  removePolygon(id: string): void {
    this.whenReady(() => {
      const shape = this.shapes.get(id)
      if (!shape) return
      forEachShape(shape, (part) => part.setMap(null))
      this.shapes.delete(id)
    })
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
}

/** A polygon region as Google has to draw it: fill and dashed outline are two objects. */
type DashedRegion = { fill: GooglePolygon; outline: GooglePolyline }

function forEachShape(
  shape: GoogleCircle | DashedRegion,
  fn: (part: { setMap(map: GoogleMap | null): void }) => void,
): void {
  if ('fill' in shape) {
    fn(shape.fill)
    fn(shape.outline)
    return
  }
  fn(shape)
}

/** Repeats the first vertex so the polyline closes the ring the polygon closes implicitly —
 *  without it the outline is missing exactly one edge, which reads as a rendering bug. */
function closedRing(path: LatLng[]): LatLng[] {
  if (path.length < 2) return path
  const first = path[0]
  const last = path[path.length - 1]
  return first.lat === last.lat && first.lng === last.lng ? path : [...path, first]
}

/** The dash itself: round dots on a transparent line, which is the only way Google exposes a
 *  dashed stroke. `scale` and `repeat` are tuned to read as a boundary at county zoom without
 *  turning into a solid line when zoomed out. */
function dashedStroke(style: Record<string, unknown>, selected?: boolean): Record<string, unknown> {
  return {
    strokeColor: style.strokeColor,
    strokeOpacity: 0,
    icons: [
      {
        icon: {
          path: 'M 0,-1 0,1',
          strokeOpacity: selected ? 1 : 0.85,
          strokeWeight: selected ? 3 : 2,
          scale: 2,
        },
        offset: '0',
        // On the 5/8/13/21… scale like any other length in this codebase, even though it is
        // handed to Google rather than to CSS — `check:tokens` scans this file too, and a
        // dash gap is exactly the kind of made-up number the check exists to catch.
        repeat: '13px',
      },
    ],
  }
}

/** Region fill/stroke — token values are resolved to real colours in `RegionPolygon.css`
 * for the fake/SVG path; a native Google shape needs concrete colours, so this reads the
 * same CSS custom properties from the document at call time rather than hardcoding hex,
 * keeping the "token-only styling" rule honest even inside the SDK's own colour options. */
function regionStyle(spec: PolygonSpec): Record<string, unknown> {
  const styles = getComputedStyle(document.documentElement)
  const tintVar = spec.prefScore == null ? '--color-border-strong' : `--scale-pref-${Math.round(spec.prefScore)}`
  const color = styles.getPropertyValue(tintVar).trim() || styles.getPropertyValue('--color-border-strong').trim()
  return {
    strokeColor: color,
    strokeOpacity: spec.selected ? 1 : 0.8,
    strokeWeight: spec.selected ? 3 : 2,
    fillColor: color,
    fillOpacity: Number(styles.getPropertyValue('--region-fill-opacity').trim() || 0.18),
  }
}
