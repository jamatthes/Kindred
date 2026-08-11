/**
 * A single date, with the trip-aware day strip.
 *
 * Almost every date the app asks for after the trip dates themselves is *inside* the trip:
 * an itinerary item, a check-in, the day a suggestion is for. When the caller supplies the
 * trip's span, those days are the primary control — a horizontal strip of "Fri 3 / Sat 4 /
 * Sun 5" chips — and the whole calendar is one press of "Any date" away. Making the common
 * case a single tap and the rare case a single extra tap is the trade the strip exists for.
 *
 * Without a trip span it is the plain field-plus-calendar, and the field is still the base:
 * the strip is another way to fill the same input, never the only way.
 */

import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'
import { CalendarSurface } from './CalendarSurface'
import type { DatePreset } from './CalendarSurface'
import { DateField } from './DateField'
import type { DateEntryMode } from './DateField'
import { PickerLayer } from './PickerLayer'
import { addDays, clampIso, daysBetween, formatLong, startOfMonth, todayIso } from './calendar'
import type { IsoDate } from './calendar'
import './pickers.css'

export type TripSpan = { start: IsoDate; end: IsoDate }

export type DatePickerProps = {
  label: string
  value: IsoDate | ''
  onChange: (value: IsoDate | '') => void
  min?: IsoDate | null
  max?: IsoDate | null
  /** When given, its days render as the primary strip and bound the calendar by default. */
  trip?: TripSpan | null
  /** Let the caller allow dates outside the trip (a travel day before it, say). */
  allowOutsideTrip?: boolean
  presets?: DatePreset[]
  error?: string | null
  hint?: ReactNode
  disabled?: boolean
  name?: string
  today?: IsoDate
  /** Forces the field's entry mode; only the fallback's own tests set it. */
  entryMode?: DateEntryMode
}

/** A strip longer than this stops being scannable and the calendar is the better answer. */
const MAX_STRIP_DAYS = 21

export function DatePicker({
  label,
  value,
  onChange,
  min = null,
  max = null,
  trip = null,
  allowOutsideTrip = false,
  presets,
  error,
  hint,
  disabled = false,
  name,
  today = todayIso(),
  entryMode,
}: DatePickerProps) {
  const [open, setOpen] = useState(false)
  const [visibleMonth, setVisibleMonth] = useState<IsoDate>(startOfMonth(value || today))

  const effectiveMin = trip && !allowOutsideTrip ? (min && min > trip.start ? min : trip.start) : min
  const effectiveMax = trip && !allowOutsideTrip ? (max && max < trip.end ? max : trip.end) : max

  const span = trip ? daysBetween(trip.start, trip.end) + 1 : 0
  const stripDays: IsoDate[] =
    trip && span > 0 && span <= MAX_STRIP_DAYS
      ? Array.from({ length: span }, (_, index) => addDays(trip.start, index))
      : []

  const openCalendar = useCallback(() => {
    if (disabled) return
    setOpen((current) => !current)
    setVisibleMonth(startOfMonth(value || clampIso(today, effectiveMin, effectiveMax)))
  }, [disabled, effectiveMax, effectiveMin, today, value])

  return (
    <div className="k-picker-single">
      <DateField
        label={label}
        name={name}
        value={value}
        onChange={onChange}
        min={effectiveMin}
        max={effectiveMax}
        error={error}
        hint={hint}
        disabled={disabled}
        open={open}
        onToggle={openCalendar}
        entryMode={entryMode}
      />

      {stripDays.length > 0 ? (
        <div className="k-picker-strip" role="group" aria-label={`${label} — days of the trip`}>
          {stripDays.map((day) => {
            const selected = day === value
            return (
              <button
                key={day}
                type="button"
                className={`k-picker-strip__day${selected ? ' k-picker-strip__day--selected' : ''}${
                  day === today ? ' k-picker-strip__day--today' : ''
                }`}
                aria-pressed={selected}
                aria-label={formatLong(day)}
                disabled={disabled}
                onClick={() => onChange(day)}
              >
                <span className="k-picker-strip__dow" aria-hidden="true">
                  {new Intl.DateTimeFormat(undefined, { weekday: 'short', timeZone: 'UTC' }).format(
                    new Date(`${day}T00:00:00Z`),
                  )}
                </span>
                <span className="k-picker-strip__num" aria-hidden="true">
                  {Number(day.slice(8, 10))}
                </span>
              </button>
            )
          })}
          <button type="button" className="k-picker-strip__more" onClick={openCalendar}>
            Any date
          </button>
        </div>
      ) : null}

      <PickerLayer open={open} title={label} onClose={() => setOpen(false)}>
        {open ? (
          <CalendarSurface
            visibleMonth={visibleMonth}
            onVisibleMonthChange={setVisibleMonth}
            selected={value || null}
            min={effectiveMin}
            max={effectiveMax}
            months={1}
            presets={presets}
            onPreset={(preset) => {
              onChange(preset.resolve(value || today).start)
              setOpen(false)
            }}
            onSelect={(date) => {
              onChange(date)
              setOpen(false)
            }}
            onClose={() => setOpen(false)}
            status={value ? `${formatLong(value)} selected.` : 'Pick a date.'}
            today={today}
          />
        ) : null}
      </PickerLayer>
    </div>
  )
}
