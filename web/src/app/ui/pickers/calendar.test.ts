import { describe, expect, it } from 'vitest'
import {
  addDays,
  addMonths,
  addYears,
  clampIso,
  daysBetween,
  formatMedium,
  isIsoDate,
  monthGrid,
  parseIso,
  parseTypedDate,
  parseTypedTime,
  snapMinutes,
  snapTime,
  timeOf,
  timeOptions,
  weekdayLabels,
} from './calendar'

describe('calendar dates', () => {
  it('rejects dates that are well-shaped but not days', () => {
    expect(parseIso('2027-02-30')).toBeNull()
    expect(parseIso('2027-13-01')).toBeNull()
    expect(parseIso('2027-00-10')).toBeNull()
    expect(isIsoDate('2028-02-29')).toBe(true) // 2028 is a leap year
    expect(isIsoDate('2027-02-29')).toBe(false)
  })

  it('adds days across month and year boundaries', () => {
    expect(addDays('2027-12-31', 1)).toBe('2028-01-01')
    expect(addDays('2027-03-01', -1)).toBe('2027-02-28')
    expect(addDays('2028-03-01', -1)).toBe('2028-02-29')
  })

  it('clamps the day when a month is shorter, so PageDown moves exactly one month', () => {
    expect(addMonths('2027-01-31', 1)).toBe('2027-02-28')
    expect(addMonths('2027-03-31', -1)).toBe('2027-02-28')
    expect(addMonths('2027-12-15', 1)).toBe('2028-01-15')
    expect(addMonths('2027-01-15', -1)).toBe('2026-12-15')
  })

  it('moves whole years, clamping 29 February', () => {
    expect(addYears('2027-06-01', 1)).toBe('2028-06-01')
    expect(addYears('2028-02-29', 1)).toBe('2029-02-28')
    expect(addYears('2027-06-01', -2)).toBe('2025-06-01')
  })

  it('clamps to a min and a max', () => {
    expect(clampIso('2027-01-01', '2027-06-01', null)).toBe('2027-06-01')
    expect(clampIso('2027-12-31', null, '2027-06-30')).toBe('2027-06-30')
    expect(clampIso('2027-06-15', '2027-06-01', '2027-06-30')).toBe('2027-06-15')
  })

  it('counts days between two dates inclusive of neither end', () => {
    expect(daysBetween('2027-12-04', '2027-12-11')).toBe(7)
    expect(daysBetween('2027-12-04', '2027-12-04')).toBe(0)
  })

  it('always builds six weeks of seven days, Monday first, starting before the 1st', () => {
    const grid = monthGrid(2027, 11) // December 2027
    expect(grid).toHaveLength(6)
    expect(grid.every((week) => week.length === 7)).toBe(true)
    // 1 Dec 2027 is a Wednesday, so a Monday-first grid opens on 29 November.
    expect(grid[0][0]).toBe('2027-11-29')
    expect(grid.flat()).toContain('2027-12-31')
    expect(new Set(grid.flat()).size).toBe(42)
  })

  it('honours a Sunday week start', () => {
    expect(monthGrid(2027, 11, 0)[0][0]).toBe('2027-11-28')
    expect(weekdayLabels(0)[0].long).toBe('Sunday')
    expect(weekdayLabels(1)[0].long).toBe('Monday')
  })

  it('formats a date without ever crossing a timezone', () => {
    // Would print 3 Dec if the date were built in a negative-offset local zone.
    expect(formatMedium('2027-12-04', 'en-GB')).toContain('4')
    expect(formatMedium('2027-12-04', 'en-GB')).toContain('2027')
  })
})

describe('typed date entry', () => {
  it('accepts ISO, day-first and compact forms', () => {
    expect(parseTypedDate('2027-12-04')).toBe('2027-12-04')
    expect(parseTypedDate('4/12/2027')).toBe('2027-12-04')
    expect(parseTypedDate('04.12.2027')).toBe('2027-12-04')
    expect(parseTypedDate('4-12-27')).toBe('2027-12-04')
    expect(parseTypedDate('20271204')).toBe('2027-12-04')
    expect(parseTypedDate('  2027-12-04  ')).toBe('2027-12-04')
  })

  it('reads an ambiguous date day-first rather than from the browser locale', () => {
    expect(parseTypedDate('03/04/2027')).toBe('2027-04-03')
  })

  it('rejects garbage instead of guessing at it', () => {
    for (const garbage of [
      '',
      'next tuesday',
      'tomorrow',
      '99/99/9999',
      '2027-02-30',
      '4/12',
      '12345',
      'Dec 4th',
      '--',
    ]) {
      expect(parseTypedDate(garbage)).toBeNull()
    }
  })
})

describe('time snapping and typed entry', () => {
  it('snaps to the nearest 15 minutes, ties upward', () => {
    expect(snapMinutes(0, 15)).toBe(0)
    expect(snapMinutes(7, 15)).toBe(0)
    expect(snapMinutes(8, 15)).toBe(15)
    expect(snapMinutes(14 * 60 + 37, 15)).toBe(14 * 60 + 30)
    expect(snapTime('14:37', 15)).toBe('14:30')
    expect(snapTime('14:38', 15)).toBe('14:45')
    expect(snapTime('14:07', 15)).toBe('14:00')
    expect(snapTime('09:00', 15)).toBe('09:00')
  })

  it('never rolls the last slot of the day over into the next day', () => {
    expect(snapTime('23:53', 15)).toBe('23:45')
    expect(snapMinutes(1439, 15)).toBe(1425)
  })

  it('honours a caller-supplied step', () => {
    expect(snapTime('10:20', 30)).toBe('10:30')
    expect(snapTime('10:10', 30)).toBe('10:00')
    expect(snapTime('10:04', 5)).toBe('10:05')
  })

  it('parses the ways people type a time', () => {
    expect(parseTypedTime('14:30')).toBe('14:30')
    expect(parseTypedTime('1430')).toBe('14:30')
    expect(parseTypedTime('2.30pm')).toBe('14:30')
    expect(parseTypedTime('2:30 PM')).toBe('14:30')
    expect(parseTypedTime('9am')).toBe('09:00')
    expect(parseTypedTime('12am')).toBe('00:00')
    expect(parseTypedTime('12pm')).toBe('12:00')
    expect(parseTypedTime('7')).toBe('07:00')
  })

  it('rejects impossible and nonsense times', () => {
    for (const garbage of ['', 'lunchtime', '25:00', '14:70', '13pm', 'half four', '::']) {
      expect(parseTypedTime(garbage)).toBeNull()
    }
  })

  it('enumerates one full day of slots', () => {
    const options = timeOptions(15)
    expect(options).toHaveLength(96)
    expect(options[0]).toBe('00:00')
    expect(options.at(-1)).toBe('23:45')
    expect(timeOf(-15)).toBe('23:45')
  })
})
