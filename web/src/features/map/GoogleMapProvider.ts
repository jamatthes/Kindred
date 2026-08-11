/**
 * GoogleMapProvider — STUB.
 *
 * The real Google Maps JS integration is the M3 `map-suggestions` implementer's job: it
 * needs the user's browser-restricted Google Maps API key, which is not yet configured
 * (`plan/architecture.md`'s Google API cost rules apply — this file adds no script tag, no
 * network call, no dependency). Every method throws immediately so a caller that
 * accidentally wires this up in dev finds out at the first map render, not from a silent
 * blank screen.
 *
 * `MapCanvas` and every pin/polygon/popover component are already provider-agnostic
 * (`MapProvider.ts`), so replacing this stub with a real implementation is the only change
 * M3 needs to make to go live — no consumer of this feature has to change.
 */

import { notWiredYet, type MapProvider } from './MapProvider'
import type {
  Bounds,
  LatLng,
  MapEventHandler,
  MapEventName,
  MapViewState,
  MarkerSpec,
  PolygonSpec,
} from './types'

const NAME = 'GoogleMapProvider'

export class GoogleMapProvider implements MapProvider {
  mount(_container: HTMLElement, _initial: MapViewState): void {
    throw notWiredYet(NAME, 'mount')
  }
  unmount(): void {
    throw notWiredYet(NAME, 'unmount')
  }
  setCenter(_center: LatLng): void {
    throw notWiredYet(NAME, 'setCenter')
  }
  panTo(_center: LatLng): void {
    throw notWiredYet(NAME, 'panTo')
  }
  setZoom(_zoom: number): void {
    throw notWiredYet(NAME, 'setZoom')
  }
  fitBounds(_bounds: Bounds, _paddingPx?: number): void {
    throw notWiredYet(NAME, 'fitBounds')
  }
  getViewState(): MapViewState {
    throw notWiredYet(NAME, 'getViewState')
  }
  addMarker(_spec: MarkerSpec): void {
    throw notWiredYet(NAME, 'addMarker')
  }
  updateMarker(_spec: MarkerSpec): void {
    throw notWiredYet(NAME, 'updateMarker')
  }
  removeMarker(_id: string): void {
    throw notWiredYet(NAME, 'removeMarker')
  }
  addPolygon(_spec: PolygonSpec): void {
    throw notWiredYet(NAME, 'addPolygon')
  }
  updatePolygon(_spec: PolygonSpec): void {
    throw notWiredYet(NAME, 'updatePolygon')
  }
  removePolygon(_id: string): void {
    throw notWiredYet(NAME, 'removePolygon')
  }
  on<K extends MapEventName>(_event: K, _handler: MapEventHandler<K>): () => void {
    throw notWiredYet(NAME, 'on')
  }
}
