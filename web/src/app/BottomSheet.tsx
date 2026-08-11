/**
 * The mobile counterpart of the desktop side panel.
 *
 * `plan/design-system.md` is explicit that analytical content never goes in a modal — on a
 * phone it goes in a sheet the user can raise, which is why this exists in M0 even though
 * no feature fills it yet. Snap points are ~40% (the action you came for, in thumb reach)
 * and ~90% (the detail behind it); the backdrop dismisses.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import './BottomSheet.css'

export type SheetSnap = 'peek' | 'full'

export type BottomSheetProps = {
  open: boolean
  title: string
  onClose: () => void
  /** Uncontrolled starting snap; the user can drag or use the handle button after that. */
  initialSnap?: SheetSnap
  children?: ReactNode
}

export function BottomSheet({
  open,
  title,
  onClose,
  initialSnap = 'peek',
  children,
}: BottomSheetProps) {
  const [snap, setSnap] = useState<SheetSnap>(initialSnap)
  const dragStart = useRef<number | null>(null)
  const sheetRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) setSnap(initialSnap)
  }, [open, initialSnap])

  // Escape closes, and focus moves into the sheet when it opens: it is a temporary
  // interaction, so it owns the keyboard while it is up.
  useEffect(() => {
    if (!open) return
    sheetRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const onPointerDown = useCallback((event: React.PointerEvent) => {
    dragStart.current = event.clientY
  }, [])

  const onPointerUp = useCallback(
    (event: React.PointerEvent) => {
      const start = dragStart.current
      dragStart.current = null
      if (start === null) return
      const travelled = event.clientY - start
      // A short flick is a snap change; a long downward drag is a dismissal.
      if (travelled < -40) setSnap('full')
      else if (travelled > 120) onClose()
      else if (travelled > 40) setSnap('peek')
    },
    [onClose],
  )

  if (!open) return null

  return (
    <div className="sheet-layer">
      <button
        type="button"
        className="sheet-backdrop"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        className={`sheet sheet--${snap}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={sheetRef}
      >
        <button
          type="button"
          className="sheet__handle"
          aria-label={snap === 'peek' ? 'Expand' : 'Collapse'}
          onClick={() => setSnap((s) => (s === 'peek' ? 'full' : 'peek'))}
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
        >
          <span className="sheet__grip" />
        </button>
        <div className="sheet__head">
          <h2 className="sheet__title">{title}</h2>
          <button type="button" className="sheet__close" onClick={onClose} aria-label="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        <div className="sheet__body">{children}</div>
      </div>
    </div>
  )
}
