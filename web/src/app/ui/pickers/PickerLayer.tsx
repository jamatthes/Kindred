/**
 * Where a picker's calendar goes: a popover on a laptop, the app's own `BottomSheet` below
 * the panel breakpoint.
 *
 * "Mobile is not a shrunken popover" (Phase 11). A popover a few hundred pixels wide,
 * anchored to a field near the bottom of a phone screen, is covered by the keyboard and
 * clipped by the viewport. The sheet is the surface the rest of the app already uses for
 * exactly this, so the picker reuses it rather than inventing a second mobile idiom.
 */

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { BottomSheet } from '../../BottomSheet'
import { PICKER_SHEET_QUERY } from '../../../design/breakpoints'

/** True below the breakpoint at which the picker becomes a sheet. Live, not read-once. */
export function useSheetLayout(): boolean {
  const [isSheet, setIsSheet] = useState(
    () => window.matchMedia?.(PICKER_SHEET_QUERY).matches ?? false,
  )
  useEffect(() => {
    const query = window.matchMedia?.(PICKER_SHEET_QUERY)
    if (!query) return
    const onChange = (event: MediaQueryListEvent) => setIsSheet(event.matches)
    query.addEventListener('change', onChange)
    setIsSheet(query.matches)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return isSheet
}

export type PickerLayerProps = {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}

export function PickerLayer({ open, title, onClose, children }: PickerLayerProps) {
  const isSheet = useSheetLayout()
  const popoverRef = useRef<HTMLDivElement>(null)

  // A popover is dismissed by clicking away from it; a sheet has a backdrop that does the
  // same job, so this listener is only wired up for the popover.
  useEffect(() => {
    if (!open || isSheet) return
    const onPointerDown = (event: PointerEvent) => {
      const node = popoverRef.current
      if (node && !node.contains(event.target as Node)) onClose()
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open, isSheet, onClose])

  if (!open) return null

  if (isSheet) {
    // Full height and scrolling: the sheet's own `full` snap, opened at that snap rather
    // than at `peek`, because a half-height calendar is a calendar with a fortnight in it.
    return (
      <BottomSheet open title={title} onClose={onClose} initialSnap="full">
        <div className="k-picker-sheet">{children}</div>
      </BottomSheet>
    )
  }

  return (
    <div className="k-picker-popover" role="dialog" aria-label={title} ref={popoverRef}>
      {children}
    </div>
  )
}
