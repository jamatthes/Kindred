/**
 * Two coupled date fields over one calendar surface — the trip-dates control.
 *
 * The coupling is the whole point, and it is a user ruling (2026-08-11) rather than a taste
 * call, because the bug it fixes was hit in the shipped admin console: a December start, and
 * then the end field's calendar opened on *August* — today's month — with every day of the
 * trip a page-and-a-half away and every impossible day clickable.
 *
 * So, exactly:
 *  - the end field's minimum is the chosen start; earlier days are announced unavailable and
 *    refuse the click;
 *  - opening the end calendar starts at the **start date's month**, never at today;
 *  - an end chosen first caps the start's maximum symmetrically;
 *  - and if a *typed* start lands after the current end, the end is cleared with an inline
 *    explanation instead of the form holding a range the server will reject.
 *
 * The surface itself is one calendar: first click locks the start, hover (or the keyboard
 * caret) paints the span, second click locks the end. Re-opening either field edits that
 * edge without starting the range over.
 */

import { useCallback, useId, useState } from 'react'
import type { ReactNode } from 'react'
import { CalendarSurface } from './CalendarSurface'
import type { DatePreset } from './CalendarSurface'
import { DateField } from './DateField'
import type { DateEntryMode } from './DateField'
import { PickerLayer } from './PickerLayer'
import {
  addDays,
  clampIso,
  daysBetween,
  formatMedium,
  startOfMonth,
  todayIso,
  weekdayIndex,
} from './calendar'
import type { IsoDate } from './calendar'
import './pickers.css'

export type DateRange = { start: IsoDate | ''; end: IsoDate | '' }

export type DateRangePickerProps = {
  value: DateRange
  /** `clearedEnd` tells the caller its end value was dropped, so it can re-validate. */
  onChange: (next: DateRange, meta: { clearedEnd: boolean }) => void
  legend?: string
  startLabel?: string
  endLabel?: string
  min?: IsoDate | null
  max?: IsoDate | null
  /** Quick picks, supplied by the caller. Trip creation passes trip-shaped ones. */
  presets?: DatePreset[]
  startError?: string | null
  endError?: string | null
  hint?: ReactNode
  disabled?: boolean
  startName?: string
  endName?: string
  today?: IsoDate
  /** Forces the fields' entry mode; only the fallback's own tests set it. */
  entryMode?: DateEntryMode
}

/**
 * The trip-shaped presets Phase 11 asks for, anchored on the chosen start (or today).
 * Exported so both the admin console and the styleguide use the same three, and so nobody
 * reaches for a "last 30 days" analytics set in a holiday planner.
 */
export const TRIP_PRESETS: DatePreset[] = [
  {
    id: 'weekend',
    label: 'This weekend',
    resolve: (anchor) => {
      // Forward to the coming Saturday; a Sunday anchor belongs to the weekend it is in.
      const dow = weekdayIndex(anchor)
      const toSaturday = dow === 0 ? -1 : (6 - dow) % 7
      const start = addDays(anchor, toSaturday)
      return { start, end: addDays(start, 1) }
    },
  },
  {
    id: 'week',
    label: 'A week',
    resolve: (anchor) => ({ start: anchor, end: addDays(anchor, 6) }),
  },
  {
    id: 'fortnight',
    label: 'A fortnight',
    resolve: (anchor) => ({ start: anchor, end: addDays(anchor, 13) }),
  },
]

type Editing = 'start' | 'end'

export function DateRangePicker({
  value,
  onChange,
  legend = 'Trip dates',
  startLabel = 'Start date',
  endLabel = 'End date',
  min = null,
  max = null,
  presets,
  startError,
  endError,
  hint,
  disabled = false,
  startName,
  endName,
  today = todayIso(),
  entryMode,
}: DateRangePickerProps) {
  const noticeId = useId()
  const [editing, setEditing] = useState<Editing | null>(null)
  const [visibleMonth, setVisibleMonth] = useState<IsoDate>(startOfMonth(today))
  const [notice, setNotice] = useState<string | null>(null)

  const start = value.start || null
  const end = value.end || null

  // The ruling, in two expressions.
  const startMax = end ?? max
  const endMin = start ?? min

  /** Where a field's calendar opens. The end's answer is "the start's month", full stop. */
  const openMonthFor = useCallback(
    (field: Editing): IsoDate => {
      // Each field opens at the range it belongs to: its own value first, then the other
      // edge's month, and only then today. Today is the last resort, never the default.
      if (field === 'start') return startOfMonth(start ?? end ?? clampIso(today, min, max))
      return startOfMonth(end ?? start ?? clampIso(today, min, max))
    },
    [end, max, min, start, today],
  )

  const openCalendar = useCallback(
    (field: Editing) => {
      if (disabled) return
      if (editing === field) {
        setEditing(null)
        return
      }
      // The month is decided *before* the surface mounts, so it never renders at today and
      // then jump-corrects to the start's month.
      setVisibleMonth(openMonthFor(field))
      setEditing(field)
    },
    [disabled, editing, openMonthFor],
  )

  const commitStart = useCallback(
    (next: IsoDate | '') => {
      if (next && end && next > end) {
        // Silently holding start > end is the failure mode this replaces: the form looked
        // fine and the save failed. Say what happened, in the place it happened.
        setNotice(
          `${formatMedium(next)} is after the old end date, so the end date has been cleared — pick a new one.`,
        )
        onChange({ start: next, end: '' }, { clearedEnd: true })
        return
      }
      setNotice(null)
      onChange({ start: next, end: value.end }, { clearedEnd: false })
    },
    [end, onChange, value.end],
  )

  const commitEnd = useCallback(
    (next: IsoDate | '') => {
      setNotice(null)
      onChange({ start: value.start, end: next }, { clearedEnd: false })
    },
    [onChange, value.start],
  )

  function onSurfaceSelect(date: IsoDate) {
    if (editing === 'start') {
      commitStart(date)
      // The first click locks the start and hands the surface to the end without a second
      // gesture; the range is two clicks, as specified.
      setEditing('end')
      setVisibleMonth((current) => (date < current ? startOfMonth(date) : current))
      return
    }
    commitEnd(date)
    setEditing(null)
  }

  function onPreset(preset: DatePreset) {
    const anchor = start ?? clampIso(today, min, max)
    const resolved = preset.resolve(anchor)
    setNotice(null)
    onChange({ start: resolved.start, end: resolved.end ?? '' }, { clearedEnd: false })
    setEditing(null)
  }

  const nights = start && end ? daysBetween(start, end) : 0
  const summary =
    start && end
      ? `${formatMedium(start)} – ${formatMedium(end)} · ${nights + 1} days`
      : start
        ? `${formatMedium(start)} — end date not chosen`
        : 'No dates chosen yet'

  const status =
    editing === 'end' && start
      ? `Start ${formatMedium(start)} selected. Now pick the end date.`
      : editing === 'start'
        ? 'Pick the start date.'
        : summary

  return (
    <fieldset className="k-picker-range" disabled={disabled}>
      <legend className="k-picker-range__legend">{legend}</legend>

      <div className="k-picker-range__fields">
        <DateField
          label={startLabel}
          name={startName}
          value={value.start}
          onChange={commitStart}
          min={min}
          max={startMax}
          error={startError}
          disabled={disabled}
          open={editing === 'start'}
          onToggle={() => openCalendar('start')}
          entryMode={entryMode}
        />
        <DateField
          label={endLabel}
          name={endName}
          value={value.end}
          onChange={commitEnd}
          min={endMin}
          max={max}
          error={endError}
          disabled={disabled}
          open={editing === 'end'}
          onToggle={() => openCalendar('end')}
          entryMode={entryMode}
          describedBy={notice ? noticeId : undefined}
        />
      </div>

      {notice ? (
        <p className="k-picker-range__notice" id={noticeId} role="status">
          {notice}
        </p>
      ) : null}
      {hint ? <p className="k-picker-range__hint">{hint}</p> : null}
      <p className="k-picker-range__summary">{summary}</p>

      <PickerLayer
        open={editing !== null}
        title={editing === 'end' ? endLabel : startLabel}
        onClose={() => setEditing(null)}
      >
        {editing ? (
          <CalendarSurface
            visibleMonth={visibleMonth}
            onVisibleMonthChange={setVisibleMonth}
            selected={editing === 'start' ? start : end}
            rangeFrom={start}
            rangeTo={end}
            min={editing === 'end' ? endMin : min}
            max={editing === 'end' ? max : startMax}
            months={2}
            presets={presets}
            onPreset={onPreset}
            onSelect={onSurfaceSelect}
            onClose={() => setEditing(null)}
            status={status}
            today={today}
          />
        ) : null}
      </PickerLayer>
    </fieldset>
  )
}
