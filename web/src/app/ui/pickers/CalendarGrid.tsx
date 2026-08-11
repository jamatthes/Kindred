/**
 * One month, as a real ARIA grid.
 *
 * The month is a table because it *is* one: the columns mean weekdays and the rows mean
 * weeks, and a screen-reader user navigating "the Thursday column" is reading the same
 * structure a sighted user scans down. `role="grid"` with a roving tabindex is what makes
 * the whole month one tab stop instead of forty-two.
 *
 * Out-of-range days carry `aria-disabled` rather than `disabled`. A disabled button is
 * removed from the focus order, and in a roving-tabindex grid that means arrow-keying across
 * a blocked-out week silently drops focus. They are announced as unavailable, they refuse
 * their click, and they stay reachable — which is also how a keyboard user discovers *where*
 * the trip's start date put the wall.
 */

import { useEffect, useRef } from 'react'
import {
  formatLong,
  formatMonthYear,
  isWithin,
  monthGrid,
  sameMonth,
  weekdayLabels,
} from './calendar'
import type { IsoDate, WeekStart } from './calendar'

export type CalendarGridProps = {
  year: number
  month: number
  /** The day that owns the grid's single tab stop. */
  focused: IsoDate
  /** Selected day(s). A single-date picker passes the same date twice or leaves `to` null. */
  selected: IsoDate | null
  rangeFrom?: IsoDate | null
  rangeTo?: IsoDate | null
  /** The live edge while the user is mid-range: hover on pointer, focus on keyboard. */
  previewTo?: IsoDate | null
  min?: IsoDate | null
  max?: IsoDate | null
  weekStartsOn?: WeekStart
  today?: IsoDate
  onSelect: (date: IsoDate) => void
  onPreview?: (date: IsoDate | null) => void
  /** Set when this grid holds the surface's focus; only then does it steal DOM focus. */
  active?: boolean
  labelId: string
}

function classesFor(options: {
  inMonth: boolean
  disabled: boolean
  isToday: boolean
  selected: boolean
  edgeStart: boolean
  edgeEnd: boolean
  inRange: boolean
  preview: boolean
}): string {
  const list = ['k-cal__day']
  if (!options.inMonth) list.push('k-cal__day--outside')
  if (options.disabled) list.push('k-cal__day--disabled')
  if (options.isToday) list.push('k-cal__day--today')
  if (options.selected) list.push('k-cal__day--selected')
  if (options.edgeStart) list.push('k-cal__day--edge-start')
  if (options.edgeEnd) list.push('k-cal__day--edge-end')
  if (options.inRange) list.push('k-cal__day--in-range')
  if (options.preview) list.push('k-cal__day--preview')
  return list.join(' ')
}

export function CalendarGrid({
  year,
  month,
  focused,
  selected,
  rangeFrom = null,
  rangeTo = null,
  previewTo = null,
  min = null,
  max = null,
  weekStartsOn = 1,
  today,
  onSelect,
  onPreview,
  active = false,
  labelId,
}: CalendarGridProps) {
  const weeks = monthGrid(year, month, weekStartsOn)
  const headers = weekdayLabels(weekStartsOn)
  const ref = useRef<HTMLTableElement>(null)

  // Roving tabindex: the focused day is the only day with tabIndex 0, and when this grid is
  // the active one the DOM focus follows the state. Guarded on `active` so a two-month
  // surface does not have both halves fighting over the caret.
  useEffect(() => {
    if (!active) return
    const cell = ref.current?.querySelector<HTMLElement>(`[data-date="${focused}"]`)
    if (cell && document.activeElement !== cell && ref.current?.contains(document.activeElement))
      cell.focus()
  }, [active, focused])

  // The span painted while the second click is still pending. Ordered so dragging the end
  // backwards past the start previews the flipped range rather than nothing.
  const previewFrom = rangeFrom && !rangeTo && previewTo ? rangeFrom : null
  const paintFrom = previewFrom
    ? previewFrom <= previewTo! ? previewFrom : previewTo!
    : rangeFrom
  const paintTo = previewFrom ? (previewFrom <= previewTo! ? previewTo! : previewFrom) : rangeTo

  return (
    <div className="k-cal__month">
      <div className="k-cal__caption" id={labelId}>
        {formatMonthYear(year, month)}
      </div>
      <table className="k-cal__grid" role="grid" aria-labelledby={labelId} ref={ref}>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header.long} scope="col" abbr={header.long} className="k-cal__weekday">
                <span aria-hidden="true">{header.short}</span>
                <span className="k-visually-hidden">{header.long}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week[0]} role="row">
              {week.map((date) => {
                const inMonth = sameMonth(date, `${year}-${String(month + 1).padStart(2, '0')}-01`)
                const disabled = !isWithin(date, min, max)
                const edgeStart = rangeFrom === date
                const edgeEnd = rangeTo === date
                const isSelected = selected === date || edgeStart || edgeEnd
                const inRange =
                  !!paintFrom && !!paintTo && date > paintFrom && date < paintTo && !disabled
                const preview = !!previewFrom && inRange

                return (
                  <td
                    key={date}
                    role="gridcell"
                    aria-selected={isSelected}
                    className="k-cal__cell"
                  >
                    <button
                      type="button"
                      data-date={date}
                      className={classesFor({
                        inMonth,
                        disabled,
                        isToday: date === today,
                        selected: isSelected,
                        edgeStart,
                        edgeEnd,
                        inRange,
                        preview,
                      })}
                      tabIndex={date === focused ? 0 : -1}
                      aria-disabled={disabled || undefined}
                      aria-current={date === today ? 'date' : undefined}
                      aria-label={formatLong(date)}
                      onClick={() => {
                        if (!disabled) onSelect(date)
                      }}
                      onMouseEnter={() => onPreview?.(date)}
                      onFocus={() => onPreview?.(date)}
                    >
                      {Number(date.slice(8, 10))}
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
