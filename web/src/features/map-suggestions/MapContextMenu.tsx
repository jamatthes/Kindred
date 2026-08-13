/**
 * The map's right-click menu — "Drop a pin here" / "Draw a region here" at the point the
 * user actually pointed at (`design.md` > "Map-first interaction model", 2; requirements S4).
 *
 * Positioned from the DOM event's own client coordinates rather than from a projection of
 * the `LatLng`, because `MapProvider` has no lat/lng → screen-point query and inventing one
 * to place a menu would be a lot of interface for a menu. The `LatLng` the provider reports
 * is what the chosen action consumes; the pixels are only ever used to put the menu under
 * the cursor.
 */

import { useEffect, useRef } from 'react'
import './mapContextMenu.css'

export type MapContextMenuProps = {
  /** Client coordinates, relative to the map container. */
  x: number
  y: number
  onDropPin: () => void
  onDrawRegion: () => void
  onClose: () => void
  disabled?: boolean
}

export function MapContextMenu({ x, y, onDropPin, onDrawRegion, onClose, disabled = false }: MapContextMenuProps) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose])

  // Focus the first item so the menu is keyboard-usable once open; the toolbar remains the
  // route in for anyone who never right-clicks at all.
  useEffect(() => {
    ref.current?.querySelector('button')?.focus()
  }, [])

  return (
    <div
      className="map-context-menu"
      role="menu"
      aria-label="Map actions"
      ref={ref}
      style={{ left: `${x}px`, top: `${y}px` }}
    >
      <button type="button" role="menuitem" onClick={onDropPin} disabled={disabled}>
        Drop a pin here
      </button>
      <button type="button" role="menuitem" onClick={onDrawRegion} disabled={disabled}>
        Draw a region here
      </button>
    </div>
  )
}
