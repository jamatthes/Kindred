/**
 * Calendar-date and clock-time arithmetic, by hand.
 *
 * `plan/features/design-system/tasks.md` Phase 11 forbids a date library, and the reason is
 * not bundle size: everything here operates on *calendar dates* ("2027-12-04" is the day the
 * ferry leaves, in the trip's timezone, which the server owns) and on *wall-clock times*
 * ("14:30" on the itinerary's 15-minute grid). Neither is an instant. A library that models
 * instants would invite a component to convert one, and the conversion would be done in the
 * browser's zone rather than the trip's — the exact bug `CLAUDE.md` keeps server-side.
 *
 * So: an ISO date is a string, month arithmetic is done on the (year, month, day) triple with
 * `Date.UTC` as the only calendar table, and no value in this file ever crosses a timezone.
 * `Intl` is used for *display* strings only.
 */

/** `YYYY-MM-DD`. The wire format, the state format and the sort key, all at once. */
export type IsoDate = string
/** `HH:MM`, 24-hour. */
export type IsoTime = string

export type Ymd = { year: number; month: number; day: number }

const ISO_SHAPE = /^(\d{4})-(\d{2})-(\d{2})$/

function pad(value: number, width = 2): string {
  return String(value).padStart(width, '0')
}

/** Days in a month. `month` is 0-based throughout this module, as in `Date`. */
export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month + 1, 0)).getUTCDate()
}

export function toIso({ year, month, day }: Ymd): IsoDate {
  return `${pad(year, 4)}-${pad(month + 1)}-${pad(day)}`
}

/**
 * Strict parse: shape *and* calendar validity. `2027-02-30` is well-shaped and not a day,
 * and a picker that accepted it would hand the server a date it will reject with a 422 the
 * user cannot act on.
 */
export function parseIso(value: string | null | undefined): Ymd | null {
  if (!value) return null
  const match = ISO_SHAPE.exec(value)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2]) - 1
  const day = Number(match[3])
  if (month < 0 || month > 11) return null
  if (day < 1 || day > daysInMonth(year, month)) return null
  return { year, month, day }
}

export function isIsoDate(value: string | null | undefined): value is IsoDate {
  return parseIso(value) !== null
}

/** Today in the *browser's* zone — only ever used to decide which month to open at. */
export function todayIso(now: Date = new Date()): IsoDate {
  return toIso({ year: now.getFullYear(), month: now.getMonth(), day: now.getDate() })
}

export function addDays(iso: IsoDate, delta: number): IsoDate {
  const parts = parseIso(iso)
  if (!parts) return iso
  const shifted = new Date(Date.UTC(parts.year, parts.month, parts.day + delta))
  return toIso({
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth(),
    day: shifted.getUTCDate(),
  })
}

/**
 * Month arithmetic clamps the day rather than overflowing: PageDown from 31 January lands on
 * 28 February, not on 3 March. Overflowing would make the key non-reversible and move focus
 * two months for one press.
 */
export function addMonths(iso: IsoDate, delta: number): IsoDate {
  const parts = parseIso(iso)
  if (!parts) return iso
  const total = parts.year * 12 + parts.month + delta
  const year = Math.floor(total / 12)
  const month = ((total % 12) + 12) % 12
  return toIso({ year, month, day: Math.min(parts.day, daysInMonth(year, month)) })
}

/** Shift+PageUp/PageDown. 29 February in a non-leap target clamps to the 28th. */
export function addYears(iso: IsoDate, delta: number): IsoDate {
  return addMonths(iso, delta * 12)
}

export function startOfMonth(iso: IsoDate): IsoDate {
  const parts = parseIso(iso)
  return parts ? toIso({ ...parts, day: 1 }) : iso
}

export function endOfMonth(iso: IsoDate): IsoDate {
  const parts = parseIso(iso)
  return parts ? toIso({ ...parts, day: daysInMonth(parts.year, parts.month) }) : iso
}

export function sameMonth(a: IsoDate | null, b: IsoDate | null): boolean {
  if (!a || !b) return false
  return a.slice(0, 7) === b.slice(0, 7)
}

/** ISO dates sort lexicographically, which is the whole point of the format. */
export function compareIso(a: IsoDate, b: IsoDate): number {
  return a < b ? -1 : a > b ? 1 : 0
}

export function isBefore(a: IsoDate, b: IsoDate): boolean {
  return a < b
}

export function isWithin(iso: IsoDate, from: IsoDate | null, to: IsoDate | null): boolean {
  if (from && iso < from) return false
  if (to && iso > to) return false
  return true
}

export function clampIso(iso: IsoDate, min?: IsoDate | null, max?: IsoDate | null): IsoDate {
  if (min && iso < min) return min
  if (max && iso > max) return max
  return iso
}

/** Inclusive day count — a Saturday-to-Sunday weekend is 2 nights' worth of 2 days. */
export function daysBetween(from: IsoDate, to: IsoDate): number {
  const a = parseIso(from)
  const b = parseIso(to)
  if (!a || !b) return 0
  const ms = Date.UTC(b.year, b.month, b.day) - Date.UTC(a.year, a.month, a.day)
  return Math.round(ms / 86_400_000)
}

/** 0 = Sunday … 6 = Saturday, for the given calendar date. */
export function weekdayIndex(iso: IsoDate): number {
  const parts = parseIso(iso)
  if (!parts) return 0
  return new Date(Date.UTC(parts.year, parts.month, parts.day)).getUTCDay()
}

export type WeekStart = 0 | 1

/**
 * Six rows of seven, always. A grid that grows a row for some months makes the popover jump
 * height as you page through it, and a jumping surface loses the pointer mid-range-drag.
 */
export function monthGrid(year: number, month: number, weekStartsOn: WeekStart = 1): IsoDate[][] {
  const first = toIso({ year, month, day: 1 })
  const offset = (weekdayIndex(first) - weekStartsOn + 7) % 7
  const gridStart = addDays(first, -offset)
  const weeks: IsoDate[][] = []
  for (let week = 0; week < 6; week += 1) {
    const row: IsoDate[] = []
    for (let day = 0; day < 7; day += 1) row.push(addDays(gridStart, week * 7 + day))
    weeks.push(row)
  }
  return weeks
}

/* ---------------------------------------------------------------------------
   Typed entry
   ------------------------------------------------------------------------ */

const NUMERIC_ENTRY = /^(\d{1,4})[/.\- ](\d{1,2})[/.\- ](\d{1,4})$/

/**
 * What a human types into the field, when the browser is not lending us a native date input.
 *
 * Accepts ISO (`2027-12-04`), day-first (`4/12/2027`, `04.12.27`, `4-12-2027`) and a bare
 * `20271204`. Day-first is the order the rest of the UI prints dates in; an ambiguous
 * `03/04/2027` is therefore 3 April, and is *not* guessed from the browser locale, because a
 * field that means different days on two laptops is worse than one that means one day.
 *
 * Returns `null` for anything else. Garbage is rejected, never coerced: `Date.parse('next
 * tuesday-ish')` returning some Tuesday is how a trip gets booked for the wrong week.
 */
export function parseTypedDate(raw: string): IsoDate | null {
  const text = raw.trim()
  if (!text) return null
  if (ISO_SHAPE.test(text)) return parseIso(text) ? text : null

  if (/^\d{8}$/.test(text)) {
    const candidate = `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
    return parseIso(candidate) ? candidate : null
  }

  const match = NUMERIC_ENTRY.exec(text)
  if (!match) return null
  const [, a, b, c] = match

  // Four digits leading means the typist wrote year-first with the wrong separator.
  let year: number
  let month: number
  let day: number
  if (a.length === 4) {
    year = Number(a)
    month = Number(b) - 1
    day = Number(c)
  } else {
    day = Number(a)
    month = Number(b) - 1
    year = Number(c)
    // A two-digit year is this century until it would be more than ~70 years hence; a trip
    // is never planned for 1998.
    if (c.length <= 2) year += year < 70 ? 2000 : 1900
  }
  if (year < 1000 || year > 9999) return null
  const candidate = toIso({ year, month, day })
  return parseIso(candidate) ? candidate : null
}

/* ---------------------------------------------------------------------------
   Display
   ------------------------------------------------------------------------ */

function utcDate(iso: IsoDate): Date {
  const parts = parseIso(iso) ?? { year: 1970, month: 0, day: 1 }
  return new Date(Date.UTC(parts.year, parts.month, parts.day))
}

/** "Saturday 4 December 2027" — the accessible name of a day cell. */
export function formatLong(iso: IsoDate, locale?: string): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(utcDate(iso))
}

/** "4 Dec 2027" — the chip and summary form. */
export function formatMedium(iso: IsoDate, locale?: string): string {
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(utcDate(iso))
}

/** "December 2027" — the grid's caption, and what a month change announces. */
export function formatMonthYear(year: number, month: number, locale?: string): string {
  return new Intl.DateTimeFormat(locale, {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month, 1)))
}

/** Column headers: `short` is drawn, `long` is what a screen reader reads. */
export function weekdayLabels(
  weekStartsOn: WeekStart = 1,
  locale?: string,
): { short: string; long: string }[] {
  const shortFmt = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' })
  const longFmt = new Intl.DateTimeFormat(locale, { weekday: 'long', timeZone: 'UTC' })
  // 2024-01-07 was a Sunday, so index 0 of this walk is Sunday whatever the locale.
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(Date.UTC(2024, 0, 7 + ((index + weekStartsOn) % 7)))
    return { short: shortFmt.format(day), long: longFmt.format(day) }
  })
}

/* ---------------------------------------------------------------------------
   Time of day
   ------------------------------------------------------------------------ */

const TIME_SHAPE = /^([01]\d|2[0-3]):([0-5]\d)$/

export function isIsoTime(value: string | null | undefined): value is IsoTime {
  return typeof value === 'string' && TIME_SHAPE.test(value)
}

export function minutesOf(time: IsoTime): number {
  const [hours, minutes] = time.split(':')
  return Number(hours) * 60 + Number(minutes)
}

export function timeOf(minutes: number): IsoTime {
  const wrapped = ((minutes % 1440) + 1440) % 1440
  return `${pad(Math.floor(wrapped / 60))}:${pad(wrapped % 60)}`
}

/**
 * Snap to the itinerary's grid (`--daytrack-snap`, mirrored in `design/snap.ts`).
 *
 * Rounds to *nearest*, and ties go up: someone who types 14:37 meant "about half past", and
 * the bar they are about to see on the day track can only start on a grid line anyway. The
 * one exception is the last step of the day — 23:53 snaps back to 23:45 rather than rolling
 * over midnight into another day's itinerary.
 */
export function snapMinutes(minutes: number, step: number): number {
  if (step <= 0) return minutes
  const snapped = Math.round(minutes / step) * step
  return snapped >= 1440 ? Math.floor((1440 - 1) / step) * step : snapped
}

export function snapTime(time: IsoTime, step: number): IsoTime {
  return timeOf(snapMinutes(minutesOf(time), step))
}

const TYPED_TIME =
  /^(\d{1,2})(?::?(\d{2}))?\s*(am|pm|a|p)?$/i

/**
 * "14:30", "1430", "2.30pm", "9 am", "0930". Anything else is `null`.
 *
 * Deliberately *not* snapped here — parsing and snapping are separate so a caller with a
 * finer grid (or none) can use the same parser, and so the tests can tell which of the two
 * is wrong when a time comes out unexpected.
 */
export function parseTypedTime(raw: string): IsoTime | null {
  const text = raw.trim().replace('.', ':')
  if (!text) return null
  const match = TYPED_TIME.exec(text)
  if (!match) return null
  let hours = Number(match[1])
  const minutes = match[2] === undefined ? 0 : Number(match[2])
  const meridiem = match[3]?.[0].toLowerCase()
  if (minutes > 59) return null
  if (meridiem) {
    if (hours < 1 || hours > 12) return null
    if (meridiem === 'p' && hours !== 12) hours += 12
    if (meridiem === 'a' && hours === 12) hours = 0
  } else if (match[2] === undefined && match[1].length === 4) {
    // "1430" with no separator: the regex read all four digits as the hour.
    hours = Number(match[1].slice(0, 2))
    const tail = Number(match[1].slice(2))
    if (hours > 23 || tail > 59) return null
    return timeOf(hours * 60 + tail)
  }
  if (hours > 23) return null
  return timeOf(hours * 60 + minutes)
}

/** Every slot on the grid, for the wheel/list on touch. */
export function timeOptions(step: number): IsoTime[] {
  const safeStep = step > 0 ? step : 15
  const out: IsoTime[] = []
  for (let minutes = 0; minutes < 1440; minutes += safeStep) out.push(timeOf(minutes))
  return out
}

/** "2:30 pm" or "14:30" depending on the reader's locale; the value stays 24-hour. */
export function formatTime(time: IsoTime, locale?: string): string {
  const [hours, minutes] = time.split(':').map(Number)
  return new Intl.DateTimeFormat(locale, {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(2024, 0, 1, hours, minutes)))
}
