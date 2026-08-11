/**
 * The calendar surface: month header, one or two grids, optional preset chips, and the one
 * keyboard map every picker in Kindred obeys.
 *
 * Two months render side by side above the panel breakpoint. A family trip is a range that
 * crosses a month boundary about half the time, and paging the calendar mid-range is where
 * the second click gets lost — so the boundary is on screen before the first click.
 *
 * Keyboard (`plan/features/design-system/tasks.md` Phase 11):
 *   ←/→        ±1 day        ↑/↓             ±1 week
 *   Home/End   week edges    PageUp/Down     ∓/±1 month
 *   Shift+PgUp/PgDn ∓/±1 year
 *   Enter/Space select       Escape          close
 *
 * Focus is state, not DOM: arrowing to a day in the next month moves the visible months and
 * the caret together, so the grid never scrolls out from under the person driving it.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { CalendarGrid } from './CalendarGrid'
import {
  addDays,
  addMonths,
  addYears,
  clampIso,
  formatMonthYear,
  isWithin,
  parseIso,
  sameMonth,
  startOfMonth,
  todayIso,
  weekdayIndex,
} from './calendar'
import type { IsoDate, WeekStart } from './calendar'

/** A caller-supplied quick pick. Trip creation passes trip-shaped ones, never analytics ones. */
export type DatePreset = {
  id: string
  label: string
  /** `anchor` is the chosen start where there is one, otherwise today. */
  resolve: (anchor: IsoDate) => { start: IsoDate; end?: IsoDate }
}

export type CalendarSurfaceProps = {
  /** The month shown top-left. Owned by the caller so the end field can open at the start. */
  visibleMonth: IsoDate
  onVisibleMonthChange: (month: IsoDate) => void
  selected: IsoDate | null
  rangeFrom?: IsoDate | null
  rangeTo?: IsoDate | null
  min?: IsoDate | null
  max?: IsoDate | null
  months?: 1 | 2
  weekStartsOn?: WeekStart
  presets?: DatePreset[]
  onPreset?: (preset: DatePreset) => void
  onSelect: (date: IsoDate) => void
  onClose?: () => void
  /** Read out politely on selection and on month change. */
  status?: string
  today?: IsoDate
}

const MONTH_JUMP_RANGE = 12

export function CalendarSurface({
  visibleMonth,
  onVisibleMonthChange,
  selected,
  rangeFrom = null,
  rangeTo = null,
  min = null,
  max = null,
  months = 1,
  weekStartsOn = 1,
  presets,
  onPreset,
  onSelect,
  onClose,
  status,
  today = todayIso(),
}: CalendarSurfaceProps) {
  const baseId = useId()
  const [focused, setFocused] = useState<IsoDate>(() => selected ?? rangeFrom ?? visibleMonth)
  const [preview, setPreview] = useState<IsoDate | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const openedRef = useRef(false)

  const shown: IsoDate[] = useMemo(
    () => (months === 2 ? [visibleMonth, addMonths(visibleMonth, 1)] : [visibleMonth]),
    [months, visibleMonth],
  )

  // Moving the caret out of the shown months pages them, keeping the caret in the first
  // month when going back and in the last when going forward.
  const moveFocus = useCallback(
    (next: IsoDate) => {
      setFocused(next)
      setPreview(next)
      const first = shown[0]
      const last = shown[shown.length - 1]
      if (next < first) onVisibleMonthChange(startOfMonth(next))
      else if (!shown.some((month) => sameMonth(month, next)) && next > last)
        onVisibleMonthChange(startOfMonth(addMonths(next, -(months - 1))))
    },
    [months, onVisibleMonthChange, shown],
  )

  // On open, the caret goes to the selected day (or the first day the caller allows), and the
  // grid takes DOM focus so the very first arrow press does something.
  useEffect(() => {
    if (openedRef.current) return
    openedRef.current = true
    const start = selected ?? rangeFrom ?? visibleMonth
    const initial = clampIso(start, min, max)
    setFocused(initial)
    const cell = rootRef.current?.querySelector<HTMLElement>(`[data-date="${initial}"]`)
    cell?.focus()
  }, [max, min, rangeFrom, selected, visibleMonth])

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      let next: IsoDate | null = null
      switch (event.key) {
        case 'ArrowLeft':
          next = addDays(focused, -1)
          break
        case 'ArrowRight':
          next = addDays(focused, 1)
          break
        case 'ArrowUp':
          next = addDays(focused, -7)
          break
        case 'ArrowDown':
          next = addDays(focused, 7)
          break
        case 'Home':
          next = addDays(focused, -((weekdayIndex(focused) - weekStartsOn + 7) % 7))
          break
        case 'End':
          next = addDays(focused, 6 - ((weekdayIndex(focused) - weekStartsOn + 7) % 7))
          break
        case 'PageUp':
          next = event.shiftKey ? addYears(focused, -1) : addMonths(focused, -1)
          break
        case 'PageDown':
          next = event.shiftKey ? addYears(focused, 1) : addMonths(focused, 1)
          break
        case 'Enter':
        case ' ':
          event.preventDefault()
          if (isWithin(focused, min, max)) onSelect(focused)
          return
        case 'Escape':
          event.preventDefault()
          onClose?.()
          return
        default:
          return
      }
      event.preventDefault()
      // Clamped, not blocked: pressing ← at the wall parks the caret on the first allowed
      // day instead of appearing to do nothing.
      moveFocus(clampIso(next, min, max))
    },
    [focused, max, min, moveFocus, onClose, onSelect, weekStartsOn],
  )

  const parts = parseIso(visibleMonth) ?? parseIso(today)!
  const years: number[] = []
  for (let year = parts.year - MONTH_JUMP_RANGE; year <= parts.year + MONTH_JUMP_RANGE; year += 1)
    years.push(year)

  function jump(year: number, month: number) {
    onVisibleMonthChange(`${String(year).padStart(4, '0')}-${String(month + 1).padStart(2, '0')}-01`)
  }

  return (
    <div className="k-cal" ref={rootRef} onKeyDown={onKeyDown}>
      <div className="k-cal__head">
        <button
          type="button"
          className="k-cal__nav"
          aria-label="Previous month"
          onClick={() => onVisibleMonthChange(addMonths(visibleMonth, -1))}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M15 5l-7 7 7 7" />
          </svg>
        </button>

        {/* Year/month jump: `no six-click month spelunking`. A trip in eighteen months is two
            selects away, not eighteen presses of the chevron. */}
        <div className="k-cal__jump">
          <label className="k-visually-hidden" htmlFor={`${baseId}-month`}>
            Month
          </label>
          <select
            id={`${baseId}-month`}
            className="k-cal__select"
            value={parts.month}
            onChange={(event) => jump(parts.year, Number(event.target.value))}
          >
            {Array.from({ length: 12 }, (_, index) => (
              <option key={index} value={index}>
                {formatMonthYear(2024, index).split(' ')[0]}
              </option>
            ))}
          </select>
          <label className="k-visually-hidden" htmlFor={`${baseId}-year`}>
            Year
          </label>
          <select
            id={`${baseId}-year`}
            className="k-cal__select"
            value={parts.year}
            onChange={(event) => jump(Number(event.target.value), parts.month)}
          >
            {years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          className="k-cal__nav"
          aria-label="Next month"
          onClick={() => onVisibleMonthChange(addMonths(visibleMonth, 1))}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      {presets && presets.length > 0 ? (
        <div className="k-cal__presets" role="group" aria-label="Quick picks">
          {presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className="k-cal__preset"
              onClick={() => onPreset?.(preset)}
            >
              {preset.label}
            </button>
          ))}
        </div>
      ) : null}

      <div
        className={`k-cal__months k-cal__months--${shown.length}`}
        onMouseLeave={() => setPreview(null)}
      >
        {shown.map((month) => {
          const monthParts = parseIso(month)!
          return (
            <CalendarGrid
              key={month}
              year={monthParts.year}
              month={monthParts.month}
              focused={focused}
              selected={selected}
              rangeFrom={rangeFrom}
              rangeTo={rangeTo}
              previewTo={preview}
              min={min}
              max={max}
              weekStartsOn={weekStartsOn}
              today={today}
              onSelect={onSelect}
              onPreview={setPreview}
              active={sameMonth(month, focused)}
              labelId={`${baseId}-${month}`}
            />
          )
        })}
      </div>

      <p className="k-cal__status" role="status" aria-live="polite">
        {status ?? ''}
      </p>
    </div>
  )
}
