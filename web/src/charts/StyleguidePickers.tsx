/**
 * `/styleguide` — the date and time pickers (design-system Phase 11).
 *
 * Everything here is live, not a screenshot: the range really couples, the calendar really
 * takes the keyboard, the time field really snaps. The only staged thing is the mid-hover
 * range, which is a pointer state and would otherwise be invisible in a still page — so that
 * one card drives `CalendarGrid` directly with the preview edge it would have had under a
 * cursor, and says so.
 *
 * Both themes render side by side, as in the tokens section: a picker is mostly a field of
 * quiet surfaces with one accent, and that is exactly the sort of thing that survives light
 * and dies in dark unless the two are compared.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { CalendarGrid } from '../app/ui/pickers/CalendarGrid'
import { DatePicker } from '../app/ui/pickers/DatePicker'
import { DateRangePicker, TRIP_PRESETS } from '../app/ui/pickers/DateRangePicker'
import type { DateRange } from '../app/ui/pickers/DateRangePicker'
import { TimeField } from '../app/ui/pickers/TimeField'
import type { IsoDate, IsoTime } from '../app/ui/pickers/calendar'
import './StyleguidePickers.css'

/** A trip far enough out that "today" is never inside it, so the strip looks the same in 2030. */
const TRIP = { start: '2027-07-17', end: '2027-07-24' }

function Panel({ theme, children }: { theme: 'light' | 'dark'; children: ReactNode }) {
  return (
    <div className="k-sg-panel" data-theme={theme}>
      <span className="k-sg-caption">{theme}</span>
      {children}
    </div>
  )
}

function RangeDemo({ initial }: { initial: DateRange }) {
  const [value, setValue] = useState<DateRange>(initial)
  return (
    <DateRangePicker
      value={value}
      onChange={setValue}
      presets={TRIP_PRESETS}
      hint="Two clicks: the first locks the start, the second the end."
    />
  )
}

function SingleDemo({ trip }: { trip?: { start: IsoDate; end: IsoDate } }) {
  const [value, setValue] = useState<IsoDate | ''>('')
  return (
    <DatePicker
      label={trip ? 'Day of the trip' : 'Date'}
      value={value}
      onChange={setValue}
      trip={trip ?? null}
    />
  )
}

function TimeDemo({ initial = '' }: { initial?: IsoTime | '' }) {
  const [value, setValue] = useState<IsoTime | ''>(initial)
  return (
    <TimeField
      label="Start time"
      value={value}
      onChange={setValue}
      hint="Type 2.30pm, or nudge with ↑ / ↓. Everything lands on the 15-minute grid."
    />
  )
}

/** The pointer state, staged: start locked on the 17th, cursor over the 24th. */
function HoverPreview({ labelId }: { labelId: string }) {
  return (
    <CalendarGrid
      year={2027}
      month={6}
      focused="2027-07-24"
      selected={null}
      rangeFrom="2027-07-17"
      rangeTo={null}
      previewTo="2027-07-24"
      onSelect={() => {}}
      labelId={labelId}
    />
  )
}

export function StyleguidePickers() {
  return (
    <div className="k-sg-pickers">
      <p className="k-styleguide__section-title">Dates and times</p>
      <p className="k-sg-pickers__note">
        Typed entry is the accessible base in all three; the calendar, the day strip and the
        time list are enhancements over the same input. Arrow keys move a day, PageUp/PageDown
        a month, Shift+PageUp/PageDown a year, Enter selects, Escape closes. Below the picker
        breakpoint each opens in the bottom sheet instead of a popover.
      </p>

      <div className="k-sg-panels">
        {(['light', 'dark'] as const).map((theme) => (
          <Panel theme={theme} key={theme}>
            <div className="k-sg-pickers__stack">
              <span className="k-sg-caption">DateRangePicker — empty, with trip presets</span>
              <RangeDemo initial={{ start: '', end: '' }} />

              <span className="k-sg-caption">
                DateRangePicker — a chosen range (its end field opens at July, not at today)
              </span>
              <RangeDemo initial={{ start: '2027-07-17', end: '2027-07-24' }} />

              <span className="k-sg-caption">DatePicker — trip-aware day strip</span>
              <SingleDemo trip={TRIP} />

              <span className="k-sg-caption">DatePicker — no trip span</span>
              <SingleDemo />

              <span className="k-sg-caption">TimeField — empty and set</span>
              <TimeDemo />
              <TimeDemo initial="14:30" />
            </div>
          </Panel>
        ))}
      </div>

      <p className="k-styleguide__section-title">Dates and times — states</p>
      <div className="k-sg-panels">
        {(['light', 'dark'] as const).map((theme) => (
          <Panel theme={theme} key={theme}>
            <div className="k-sg-pickers__stack">
              <span className="k-sg-caption">Error — the server blamed the end date</span>
              <DateRangePicker
                value={{ start: '2027-07-17', end: '2027-07-10' }}
                onChange={() => {}}
                endError="The end date cannot be before the start date."
              />

              <span className="k-sg-caption">Disabled — the End stage is read-only</span>
              <DateRangePicker
                value={{ start: '2027-07-17', end: '2027-07-24' }}
                onChange={() => {}}
                disabled
              />

              <span className="k-sg-caption">TimeField — error and disabled</span>
              <TimeField
                label="Start time"
                value="quarter past"
                onChange={() => {}}
                error="Enter a time like 14:30 or 2.30pm."
              />
              <TimeField label="Start time" value="14:30" onChange={() => {}} disabled />

              <span className="k-sg-caption">
                Range mid-hover — staged: start locked on the 17th, pointer over the 24th
              </span>
              <HoverPreview labelId={`k-sg-hover-preview-${theme}`} />
            </div>
          </Panel>
        ))}
      </div>
    </div>
  )
}
