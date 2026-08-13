/**
 * The shell's right-hand panel, filled by whichever screen is showing.
 *
 * `Shell` renders the panel; a feature screen owns the data that belongs in it. Passing the
 * content down as a `sidePanel` prop would mean the route — which knows nothing about
 * suggestions, selection or loading state — reaching into the screen's own hooks to build it.
 * So the screen portals its content into the panel instead, and tells the shell it has done
 * so through this store, which is the one thing a portal cannot say for itself: the shell has
 * to know whether to draw its "select something…" placeholder or get out of the way.
 *
 * Deliberately a two-line external store rather than context: the value changes on selection,
 * and a context provider high enough to hold it would re-render the whole shell every time a
 * pin is clicked.
 */

import { useSyncExternalStore } from 'react'

/** The portal target inside the shell's `<aside>`. */
export const SIDE_PANEL_SLOT_ID = 'side-panel-slot'

let filled = false
const listeners = new Set<() => void>()

/** Called by a screen that is portaling content into the panel (and again with `false` when
 *  it stops), so the placeholder and the real content never show at once. */
export function setSidePanelFilled(next: boolean): void {
  if (filled === next) return
  filled = next
  listeners.forEach((listener) => listener())
}

export function useSidePanelFilled(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => filled,
    () => false,
  )
}
