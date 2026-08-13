/**
 * Places a card against a point on the map so it stays fully visible.
 *
 * A card pinned to a place is only useful if you can read it. Anchoring alone is not enough:
 * click a place near the top of the map and a card that always sits *above* its point is
 * pushed off the edge; click one near a side and it hangs over it. So this hook does what a
 * real map popup does — **flip** below the point when there is no room above, and **clamp**
 * horizontally to the map's own box.
 *
 * Clamping moves the card without moving the place it describes, so the tail has to stop
 * being "centred" and start tracking the point: `--tail-x` is the tail's offset within the
 * card, which is why the CSS positions the tail from that variable rather than at 50%.
 *
 * Measured, not guessed. The card's height depends on its content (a create form and a
 * two-line preview card differ by a factor of five), so the decision to flip is taken after
 * layout with a real `getBoundingClientRect`, in `useLayoutEffect`, before the browser
 * paints — a guess would show the card in the wrong place for one frame.
 */

import { useCallback, useLayoutEffect, useRef, useState } from 'react'

/** Breathing room between the card and the map's edge. */
const EDGE_MARGIN_PX = 12
/** How close the tail may get to a rounded corner before it starts to look detached. */
const TAIL_INSET_PX = 20
/** Kept in step with `--popover-tail-size`; the gap the tail occupies between card and point. */
const TAIL_SIZE_PX = 12

export type AnchoredPlacement = {
  left: number
  top: number
  /** The card sits below its point (tail on top) because there was no room above. */
  below: boolean
  /** Tail offset from the card's left edge, so it keeps pointing at the place after clamping. */
  tailX: number
}

export type UseAnchoredPlacementResult = {
  /** Attach to the anchored element. */
  ref: (node: HTMLElement | null) => void
  placement: AnchoredPlacement | null
}

export function useAnchoredPlacement(
  point: { x: number; y: number } | null,
  container: HTMLElement | null,
): UseAnchoredPlacementResult {
  const [node, setNode] = useState<HTMLElement | null>(null)
  const [placement, setPlacement] = useState<AnchoredPlacement | null>(null)
  const ref = useCallback((next: HTMLElement | null) => setNode(next), [])
  // Compared before setting state: this runs on every map move, and re-rendering the card 60
  // times a second with identical numbers would make a drag feel worse, not better.
  const lastRef = useRef<string>('')

  useLayoutEffect(() => {
    if (!node || !container || !point) {
      lastRef.current = ''
      setPlacement(null)
      return
    }

    const card = node.getBoundingClientRect()
    const box = container.getBoundingClientRect()
    const maxLeft = Math.max(EDGE_MARGIN_PX, box.width - card.width - EDGE_MARGIN_PX)
    const left = Math.min(Math.max(point.x - card.width / 2, EDGE_MARGIN_PX), maxLeft)

    // Flip when the card would not fit above its point — but only if there is more room
    // below, otherwise flipping trades one clipped edge for another.
    const roomAbove = point.y - EDGE_MARGIN_PX - TAIL_SIZE_PX
    const roomBelow = box.height - point.y - EDGE_MARGIN_PX - TAIL_SIZE_PX
    const below = card.height > roomAbove && roomBelow > roomAbove

    const rawTop = below ? point.y + TAIL_SIZE_PX : point.y - card.height - TAIL_SIZE_PX
    const maxTop = Math.max(EDGE_MARGIN_PX, box.height - card.height - EDGE_MARGIN_PX)
    const top = Math.min(Math.max(rawTop, EDGE_MARGIN_PX), maxTop)

    const tailX = Math.min(Math.max(point.x - left, TAIL_INSET_PX), Math.max(card.width - TAIL_INSET_PX, TAIL_INSET_PX))

    const key = `${left}|${top}|${below}|${tailX}`
    if (key === lastRef.current) return
    lastRef.current = key
    setPlacement({ left, top, below, tailX })
  }, [node, container, point?.x, point?.y])

  return { ref, placement }
}
