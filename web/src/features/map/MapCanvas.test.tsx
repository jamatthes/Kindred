import { describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'
import { MapCanvas } from './MapCanvas'
import type { MapProvider } from './MapProvider'
import type { MapEventHandler, MapEventName, MarkerSpec, PolygonSpec } from './types'

/** A minimal recording `MapProvider` — isolates `MapCanvas`'s diff logic from
 *  `FakeMapProvider`'s own DOM-building, which has its own test file. */
function makeMockProvider() {
  const calls: string[] = []
  const markers = new Map<string, MarkerSpec>()
  const polygons = new Map<string, PolygonSpec>()
  const handlers = new Map<MapEventName, Set<(p: unknown) => void>>()

  const provider: MapProvider = {
    mount: vi.fn((_c, _v) => calls.push('mount')),
    unmount: vi.fn(() => calls.push('unmount')),
    setCenter: vi.fn(() => calls.push('setCenter')),
    panTo: vi.fn(() => calls.push('panTo')),
    setZoom: vi.fn(() => calls.push('setZoom')),
    fitBounds: vi.fn(() => calls.push('fitBounds')),
    getViewState: vi.fn(() => ({ center: { lat: 0, lng: 0 }, zoom: 1 })),
    addMarker: vi.fn((spec: MarkerSpec) => {
      calls.push(`addMarker:${spec.id}`)
      markers.set(spec.id, spec)
    }),
    updateMarker: vi.fn((spec: MarkerSpec) => {
      calls.push(`updateMarker:${spec.id}`)
      markers.set(spec.id, spec)
    }),
    removeMarker: vi.fn((id: string) => {
      calls.push(`removeMarker:${id}`)
      markers.delete(id)
    }),
    addPolygon: vi.fn((spec: PolygonSpec) => {
      calls.push(`addPolygon:${spec.id}`)
      polygons.set(spec.id, spec)
    }),
    updatePolygon: vi.fn((spec: PolygonSpec) => {
      calls.push(`updatePolygon:${spec.id}`)
      polygons.set(spec.id, spec)
    }),
    removePolygon: vi.fn((id: string) => {
      calls.push(`removePolygon:${id}`)
      polygons.delete(id)
    }),
    on: vi.fn(<K extends MapEventName>(event: K, handler: MapEventHandler<K>) => {
      if (!handlers.has(event)) handlers.set(event, new Set())
      handlers.get(event)!.add(handler as (p: unknown) => void)
      return () => handlers.get(event)!.delete(handler as (p: unknown) => void)
    }),
  }

  /** Fires every handler currently registered for `event` — the mock's stand-in for "the
   *  provider's own SDK fired a real click", used to prove *which* callback instance
   *  actually runs, not just that `provider.on` was called once at mount. */
  function emit<K extends MapEventName>(event: K, payload: unknown) {
    for (const handler of handlers.get(event) ?? []) handler(payload)
  }

  return { provider, calls, markers, polygons, emit }
}

const m1: MarkerSpec = {
  id: 'm1',
  kind: 'suggestion',
  position: { lat: 1, lng: 1 },
  category: 'meal',
  status: 'proposed',
}
const m2: MarkerSpec = {
  id: 'm2',
  kind: 'suggestion',
  position: { lat: 2, lng: 2 },
  category: 'activity',
  status: 'proposed',
}

describe('MapCanvas — provider lifecycle', () => {
  it('mounts the provider exactly once with the initial view', () => {
    const { provider, calls } = makeMockProvider()
    render(<MapCanvas createProvider={() => provider} center={{ lat: 1, lng: 1 }} zoom={3} />)
    expect(calls).toEqual(['mount'])
    expect(provider.mount).toHaveBeenCalledWith(expect.any(HTMLElement), { center: { lat: 1, lng: 1 }, zoom: 3 })
  })

  it('unmounts the provider on unmount', () => {
    const { provider } = makeMockProvider()
    const { unmount } = render(<MapCanvas createProvider={() => provider} center={{ lat: 0, lng: 0 }} zoom={1} />)
    unmount()
    expect(provider.unmount).toHaveBeenCalledTimes(1)
  })

  it('setCenter/setZoom are called on prop changes, not a remount', () => {
    const { provider, calls } = makeMockProvider()
    const { rerender } = render(<MapCanvas createProvider={() => provider} center={{ lat: 1, lng: 1 }} zoom={3} />)
    rerender(<MapCanvas createProvider={() => provider} center={{ lat: 2, lng: 2 }} zoom={4} />)
    expect(calls.filter((c) => c === 'mount')).toHaveLength(1)
    expect(provider.setCenter).toHaveBeenCalledWith({ lat: 2, lng: 2 })
    expect(provider.setZoom).toHaveBeenCalledWith(4)
  })
})

describe('MapCanvas — marker diffing', () => {
  it('adds markers present in props, updates existing ones, removes vanished ones', () => {
    const { provider, calls } = makeMockProvider()
    const { rerender } = render(
      <MapCanvas createProvider={() => provider} center={{ lat: 0, lng: 0 }} zoom={1} markers={[m1, m2]} />,
    )
    expect(calls).toEqual(['mount', 'addMarker:m1', 'addMarker:m2'])

    calls.length = 0
    rerender(
      <MapCanvas
        createProvider={() => provider}
        center={{ lat: 0, lng: 0 }}
        zoom={1}
        markers={[{ ...m1, status: 'approved' }]}
      />,
    )
    // Order between the removal and update passes is not a contract worth pinning down.
    expect(calls.sort()).toEqual(['removeMarker:m2', 'updateMarker:m1'])
  })
})

describe('MapCanvas — polygon diffing', () => {
  it('adds/updates/removes polygons the same way as markers', () => {
    const { provider, calls } = makeMockProvider()
    const p1: PolygonSpec = { id: 'p1', shape: 'polygon', path: [{ lat: 0, lng: 0 }] }
    const { rerender } = render(
      <MapCanvas createProvider={() => provider} center={{ lat: 0, lng: 0 }} zoom={1} polygons={[p1]} />,
    )
    expect(calls).toContain('addPolygon:p1')

    calls.length = 0
    rerender(<MapCanvas createProvider={() => provider} center={{ lat: 0, lng: 0 }} zoom={1} polygons={[]} />)
    expect(calls).toEqual(['removePolygon:p1'])
  })
})

describe('MapCanvas — events', () => {
  it('wires onMarkerClick/onMapClick to provider.on and invokes them on a real event', () => {
    const { provider, emit } = makeMockProvider()
    const onMarkerClick = vi.fn()
    const onMapClick = vi.fn()
    const { unmount } = render(
      <MapCanvas
        createProvider={() => provider}
        center={{ lat: 0, lng: 0 }}
        zoom={1}
        onMarkerClick={onMarkerClick}
        onMapClick={onMapClick}
      />,
    )
    expect(provider.on).toHaveBeenCalledWith('markerClick', expect.any(Function))
    expect(provider.on).toHaveBeenCalledWith('mapClick', expect.any(Function))

    emit('markerClick', { id: 'm1' })
    expect(onMarkerClick).toHaveBeenCalledWith({ id: 'm1' })
    emit('mapClick', { position: { lat: 1, lng: 2 } })
    expect(onMapClick).toHaveBeenCalledWith({ position: { lat: 1, lng: 2 } })

    unmount()
  })

  it('always invokes the latest handler instance, never a closure captured at mount', () => {
    // The regression this guards: MapCanvas's mount effect runs exactly once (deps: []),
    // so subscribing a caller's callback *directly* would freeze whatever closure that
    // callback happened to be on the first render — found for real via
    // MapSuggestionsScreen's onMapClick, which closes over `creating`/`createMode` and was
    // silently always evaluating their mount-time values on every later click.
    const { provider, emit } = makeMockProvider()
    let seenBy: 'first' | 'second' | null = null
    const firstHandler: MapEventHandler<'mapClick'> = () => {
      seenBy = 'first'
    }
    const secondHandler: MapEventHandler<'mapClick'> = () => {
      seenBy = 'second'
    }

    const { rerender } = render(
      <MapCanvas createProvider={() => provider} center={{ lat: 0, lng: 0 }} zoom={1} onMapClick={firstHandler} />,
    )
    rerender(
      <MapCanvas createProvider={() => provider} center={{ lat: 0, lng: 0 }} zoom={1} onMapClick={secondHandler} />,
    )

    emit('mapClick', { position: { lat: 5, lng: 5 } })
    expect(seenBy).toBe('second')
  })

  it('exposes the live provider instance via onProviderReady', () => {
    const { provider } = makeMockProvider()
    const onProviderReady = vi.fn()
    render(
      <MapCanvas
        createProvider={() => provider}
        center={{ lat: 0, lng: 0 }}
        zoom={1}
        onProviderReady={onProviderReady}
      />,
    )
    expect(onProviderReady).toHaveBeenCalledWith(provider)
  })
})
