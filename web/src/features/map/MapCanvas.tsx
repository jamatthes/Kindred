/**
 * MapCanvas — hosts a `MapProvider`, sized by its container, theme-aware.
 *
 * Declarative on the outside (`markers`/`polygons`/`center`/`zoom` props, like any other
 * React component), imperative underneath: it diffs the incoming props against what the
 * provider currently holds and issues add/update/remove calls, because that is the
 * contract every real map SDK actually has. This is the one place in the feature that
 * knows both worlds; every other component here only ever sees one.
 *
 * The provider is supplied by the caller (`createProvider`), not hardcoded, so the
 * styleguide and every test use `FakeMapProvider` while a real screen (built at M3) passes
 * `GoogleMapProvider` — nothing else about this component changes.
 */

import { useEffect, useRef } from 'react'
import type { MapProvider } from './MapProvider'
import type { LatLng, MapEventHandler, MarkerSpec, PolygonSpec } from './types'
import './MapCanvas.css'

export type MapCanvasProps = {
  createProvider: () => MapProvider
  center: LatLng
  zoom: number
  markers?: MarkerSpec[]
  polygons?: PolygonSpec[]
  onMarkerClick?: MapEventHandler<'markerClick'>
  onMarkerHover?: MapEventHandler<'markerHover'>
  onPolygonClick?: MapEventHandler<'polygonClick'>
  onMapClick?: MapEventHandler<'mapClick'>
  /** For tests/styleguide to reach the live provider instance without a ref-forwarding
   *  dance — the provider itself is the imperative surface, so exposing it directly is
   *  more honest than inventing a second one. */
  onProviderReady?: (provider: MapProvider) => void
  className?: string
}

export function MapCanvas({
  createProvider,
  center,
  zoom,
  markers = [],
  polygons = [],
  onMarkerClick,
  onMarkerHover,
  onPolygonClick,
  onMapClick,
  onProviderReady,
  className,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const providerRef = useRef<MapProvider | null>(null)
  const markerIdsRef = useRef<Set<string>>(new Set())
  const polygonIdsRef = useRef<Set<string>>(new Set())
  const skipNextCenterRef = useRef(true)
  const skipNextZoomRef = useRef(true)

  // Every prop this effect reads is captured fresh via refs updated on each render, so the
  // effect body itself can stay deps-free (`[]`) and genuinely run once per mount — a
  // caller passing an inline `() => new FakeMapProvider()` (a new function identity every
  // render, which is the natural way to write it) must not cause a remount.
  const latestPropsRef = useRef({ center, zoom, onMarkerClick, onMarkerHover, onPolygonClick, onMapClick, onProviderReady })
  latestPropsRef.current = { center, zoom, onMarkerClick, onMarkerHover, onPolygonClick, onMapClick, onProviderReady }
  const createProviderRef = useRef(createProvider)
  createProviderRef.current = createProvider

  // Mount once. `center`/`zoom` at mount time only seed the initial view; subsequent
  // changes go through setCenter/setZoom below rather than remounting, so an in-progress
  // pan by the user is never clobbered by an unrelated prop update.
  useEffect(() => {
    const { center: initialCenter, zoom: initialZoom, onMarkerClick, onMarkerHover, onPolygonClick, onMapClick, onProviderReady } =
      latestPropsRef.current
    const provider = createProviderRef.current()
    providerRef.current = provider
    if (containerRef.current) {
      provider.mount(containerRef.current, { center: initialCenter, zoom: initialZoom })
    }
    onProviderReady?.(provider)

    const offClick = onMarkerClick ? provider.on('markerClick', onMarkerClick) : undefined
    const offHover = onMarkerHover ? provider.on('markerHover', onMarkerHover) : undefined
    const offPolyClick = onPolygonClick ? provider.on('polygonClick', onPolygonClick) : undefined
    const offMapClick = onMapClick ? provider.on('mapClick', onMapClick) : undefined

    return () => {
      offClick?.()
      offHover?.()
      offPolyClick?.()
      offMapClick?.()
      provider.unmount()
      providerRef.current = null
      markerIdsRef.current = new Set()
      polygonIdsRef.current = new Set()
      skipNextCenterRef.current = true
      skipNextZoomRef.current = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    // The first run merely reports the value `mount` already seeded above.
    if (skipNextCenterRef.current) {
      skipNextCenterRef.current = false
      return
    }
    providerRef.current?.setCenter(center)
  }, [center.lat, center.lng])

  useEffect(() => {
    if (skipNextZoomRef.current) {
      skipNextZoomRef.current = false
      return
    }
    providerRef.current?.setZoom(zoom)
  }, [zoom])

  useEffect(() => {
    const provider = providerRef.current
    if (!provider) return
    const nextIds = new Set(markers.map((m) => m.id))
    const currentIds = markerIdsRef.current

    for (const id of currentIds) {
      if (!nextIds.has(id)) provider.removeMarker(id)
    }
    for (const marker of markers) {
      if (currentIds.has(marker.id)) provider.updateMarker(marker)
      else provider.addMarker(marker)
    }
    markerIdsRef.current = nextIds
    // Re-run whenever the marker list's identity/content changes; a shallow array
    // reference check is intentionally not enough here (spec fields like `status` mutate).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markers])

  useEffect(() => {
    const provider = providerRef.current
    if (!provider) return
    const nextIds = new Set(polygons.map((p) => p.id))
    const currentIds = polygonIdsRef.current

    for (const id of currentIds) {
      if (!nextIds.has(id)) provider.removePolygon(id)
    }
    for (const polygon of polygons) {
      if (currentIds.has(polygon.id)) provider.updatePolygon(polygon)
      else provider.addPolygon(polygon)
    }
    polygonIdsRef.current = nextIds
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [polygons])

  return <div ref={containerRef} className={['k-map-canvas', className].filter(Boolean).join(' ')} />
}
