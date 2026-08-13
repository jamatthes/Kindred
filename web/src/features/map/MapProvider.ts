/**
 * `MapProvider` — the provider-agnostic map interface.
 *
 * `MapCanvas` talks to exactly this surface and never to a concrete SDK. Two
 * implementations exist today:
 *  - `FakeMapProvider` — deterministic, DOM-based, used by every test and the styleguide.
 *  - `GoogleMapProvider` — a stub. The real Google Maps JS wiring is the M3 agent's job
 *    (it needs the user's browser API key, not yet configured); calling any method
 *    throws a clear "not wired yet" error rather than failing silently.
 *
 * Imperative by design, matching how every map SDK (Google, Mapbox, Leaflet) actually
 * works: `mount` once, then issue commands. `MapCanvas` is the declarative React layer
 * on top — it diffs `markers`/`polygons` props against what the provider currently holds
 * and calls add/update/remove accordingly, so a future `GoogleMapProvider` slots in
 * without `MapCanvas` changing.
 */

import type {
  Bounds,
  LatLng,
  MapEventHandler,
  MapEventName,
  MapMountOptions,
  MapViewState,
  MarkerSpec,
  PolygonSpec,
} from './types'

export interface MapProvider {
  /** Attaches the provider to a live container element and renders the initial view. */
  mount(container: HTMLElement, initial: MapMountOptions): void
  /** Tears down everything `mount` created. Safe to call at most once per `mount`. */
  unmount(): void

  setCenter(center: LatLng): void
  /** Same as `setCenter`, but implementations may animate; `FakeMapProvider` does not. */
  panTo(center: LatLng): void
  setZoom(zoom: number): void
  /** Frames `bounds` in the viewport, with `paddingPx` of margin on every side. */
  fitBounds(bounds: Bounds, paddingPx?: number): void
  getViewState(): MapViewState

  /**
   * Where `position` currently sits, in pixels relative to the map container's top-left.
   * `null` when the provider cannot answer yet (not mounted, or the SDK's projection is not
   * ready) — callers must treat that as "don't draw the anchored thing yet", never as 0,0.
   *
   * This is what lets a React-rendered card sit *over* the place it describes instead of
   * parked in a corner. Pair it with the `viewChange` event: the answer is only true for the
   * current view.
   */
  projectToContainerPoint(position: LatLng): { x: number; y: number } | null

  /** Adds a marker. Throws if `spec.id` is already present — callers diff, they don't
   *  guess, so a duplicate add is a bug in the caller. */
  addMarker(spec: MarkerSpec): void
  /** Replaces the marker at `spec.id` wholesale. Throws if it is not present. */
  updateMarker(spec: MarkerSpec): void
  /** No-ops if `id` is not present — removal races with unmount are expected. */
  removeMarker(id: string): void

  addPolygon(spec: PolygonSpec): void
  updatePolygon(spec: PolygonSpec): void
  removePolygon(id: string): void

  /** Subscribes to a map event; returns an unsubscribe function. */
  on<K extends MapEventName>(event: K, handler: MapEventHandler<K>): () => void
}

/** Shared "not implemented" message shape for provider stubs. */
export function notWiredYet(providerName: string, method: string): Error {
  return new Error(
    `${providerName}.${method}() is not wired yet — the real integration is built in the ` +
      `M3 map-suggestions milestone once the browser Google Maps API key is configured. ` +
      `Use FakeMapProvider for tests and the styleguide.`,
  )
}
