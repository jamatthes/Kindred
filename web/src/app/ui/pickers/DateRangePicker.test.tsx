/**
 * The range-coupling ruling of 2026-08-11, under test.
 *
 * These are not generic widget tests: each one pins a clause of the ruling, and the first
 * three describe the bug that was actually hit — a December start whose end picker opened on
 * August with every impossible day clickable.
 */

import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { DateRangePicker, TRIP_PRESETS } from './DateRangePicker'
import type { DateRange } from './DateRangePicker'

const TODAY = '2026-08-11' // the day of the ruling: a start in December is four months away

function Harness({
  initial = { start: '', end: '' },
  entryMode,
}: {
  initial?: DateRange
  entryMode?: 'native' | 'text'
}) {
  const [value, setValue] = useState<DateRange>(initial)
  return (
    <DateRangePicker
      value={value}
      onChange={(next) => setValue(next)}
      presets={TRIP_PRESETS}
      today={TODAY}
      entryMode={entryMode}
    />
  )
}

const openEnd = () => fireEvent.click(screen.getByRole('button', { name: /End date — open calendar/ }))
const openStart = () =>
  fireEvent.click(screen.getByRole('button', { name: /Start date — open calendar/ }))

/* The open popover is a dialog labelled by the same field name, so these ask for the input
   specifically rather than for anything the label text reaches. */
const startInput = () => screen.getByLabelText('Start date', { selector: 'input' })
const endInput = () => screen.getByLabelText('End date', { selector: 'input' })

function grid() {
  return screen.getAllByRole('grid')
}

/**
 * A day cell by its ISO date. Queried by `data-date` rather than by accessible name because
 * two months are on screen and "3 December 2026" is a substring of "13 December 2026" — the
 * first month's cell is the one every assertion here means.
 */
function day(iso: string): HTMLElement {
  const cells = document.querySelectorAll<HTMLElement>(`[data-date="${iso}"]`)
  expect(cells.length).toBeGreaterThan(0)
  return cells[0]
}

describe('DateRangePicker — range coupling', () => {
  it('opens the end calendar at the start date’s month, never at today', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '' }} />)
    openEnd()
    const captions = grid().map((table) => table.getAttribute('aria-labelledby'))
    expect(captions).toHaveLength(2)
    // December is on screen the moment it opens — and August, today's month, is not.
    expect(screen.getByText('December 2026')).toBeInTheDocument()
    expect(screen.getByText('January 2027')).toBeInTheDocument()
    expect(screen.queryByText('August 2026')).not.toBeInTheDocument()
  })

  it('disables every day before the start in the end calendar', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '' }} />)
    openEnd()
    expect(day('2026-12-03')).toHaveAttribute('aria-disabled', 'true')
    expect(day('2026-12-04')).not.toHaveAttribute('aria-disabled')
    expect(day('2026-12-05')).not.toHaveAttribute('aria-disabled')
  })

  it('refuses the click on a disabled pre-start day', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '' }} />)
    openEnd()
    fireEvent.click(day('2026-12-01'))
    expect(endInput()).toHaveValue('')
    // Still open, still asking for an end date.
    expect(screen.getByText('December 2026')).toBeInTheDocument()
  })

  it('mirrors the rule: an end chosen first caps the start’s maximum', () => {
    render(<Harness initial={{ start: '', end: '2026-12-11' }} />)
    openStart()
    expect(day('2026-12-12')).toHaveAttribute('aria-disabled', 'true')
    expect(day('2026-12-11')).not.toHaveAttribute('aria-disabled')
  })

  it('clears the end, with an explanation, when a typed start lands after it', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '2026-12-11' }} />)
    fireEvent.change(startInput(), { target: { value: '2026-12-20' } })
    expect(endInput()).toHaveValue('')
    const notice = screen.getByRole('status')
    expect(notice).toHaveTextContent(/end date has been cleared/i)
    // The explanation is wired to the field it is about, not just floated near it.
    expect(endInput().getAttribute('aria-describedby')).toContain(
      notice.id,
    )
  })

  it('keeps a still-valid end when the start moves earlier', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '2026-12-11' }} />)
    fireEvent.change(startInput(), { target: { value: '2026-12-01' } })
    expect(endInput()).toHaveValue('2026-12-11')
    expect(screen.queryByText(/has been cleared/i)).not.toBeInTheDocument()
  })
})

describe('DateRangePicker — two clicks', () => {
  it('locks the start on the first click and the end on the second', () => {
    render(<Harness />)
    openStart()
    fireEvent.click(day('2026-08-04'))
    // The surface stays up and hands itself to the end date — no second gesture.
    expect(screen.getByText(/Now pick the end date/)).toBeInTheDocument()
    fireEvent.click(day('2026-08-11'))
    expect(startInput()).toHaveValue('2026-08-04')
    expect(endInput()).toHaveValue('2026-08-11')
    expect(screen.queryByRole('grid')).not.toBeInTheDocument()
  })

  it('paints the days between the edges as in-range', () => {
    render(<Harness initial={{ start: '2026-08-04', end: '2026-08-08' }} />)
    openStart()
    expect(day('2026-08-06').className).toContain('in-range')
    expect(day('2026-08-04').className).toContain('edge-start')
    expect(day('2026-08-08').className).toContain('edge-end')
    expect(day('2026-08-10').className).not.toContain('in-range')
  })

  it('previews the span under the pointer before the second click', () => {
    render(<Harness />)
    openStart()
    fireEvent.click(day('2026-08-04'))
    fireEvent.mouseEnter(day('2026-08-09'))
    expect(day('2026-08-06').className).toContain('preview')
    expect(day('2026-08-12').className).not.toContain('preview')
  })

  it('shows two months side by side so a range can cross the boundary', () => {
    render(<Harness />)
    openStart()
    expect(grid()).toHaveLength(2)
    expect(screen.getByText('August 2026')).toBeInTheDocument()
    expect(screen.getByText('September 2026')).toBeInTheDocument()
  })
})

describe('DateRangePicker — presets', () => {
  it('offers only the caller’s presets, and fills both edges in one click', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '' }} />)
    openStart()
    fireEvent.click(screen.getByRole('button', { name: 'A week' }))
    expect(startInput()).toHaveValue('2026-12-04')
    expect(endInput()).toHaveValue('2026-12-10')
  })

  it('anchors a weekend preset on the coming Saturday', () => {
    // 2026-08-11 is a Tuesday; the coming Saturday is the 15th.
    expect(TRIP_PRESETS[0].resolve('2026-08-11')).toEqual({
      start: '2026-08-15',
      end: '2026-08-16',
    })
    // A Sunday belongs to the weekend it is already in.
    expect(TRIP_PRESETS[0].resolve('2026-08-16')).toEqual({
      start: '2026-08-15',
      end: '2026-08-16',
    })
  })

  it('renders no preset group when the caller supplies none', () => {
    render(
      <DateRangePicker value={{ start: '', end: '' }} onChange={() => {}} today={TODAY} />,
    )
    openStart()
    expect(screen.queryByRole('group', { name: 'Quick picks' })).not.toBeInTheDocument()
  })
})

describe('DateRangePicker — typed entry and errors', () => {
  /* The text-entry branch: what the field does where `<input type="date">` does not exist.
     Everywhere else the browser's own date input is the base and does the sanitising. */
  it('rejects garbage with an inline explanation, and commits nothing', () => {
    render(<Harness entryMode="text" />)
    const field = startInput()
    fireEvent.change(field, { target: { value: 'next tuesday' } })
    fireEvent.blur(field)
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a date as DD/MM/YYYY.')
    expect(screen.getByText('No dates chosen yet')).toBeInTheDocument()
  })

  it('accepts a day-first typed date and clears the complaint', () => {
    render(<Harness entryMode="text" />)
    const field = startInput()
    fireEvent.change(field, { target: { value: 'rubbish' } })
    fireEvent.blur(field)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    fireEvent.change(field, { target: { value: '4/12/2026' } })
    fireEvent.blur(field)
    expect(field).toHaveValue('2026-12-04')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('uses the browser’s own date input when there is one', () => {
    render(<Harness />)
    expect(startInput()).toHaveAttribute('type', 'date')
  })

  it('surfaces a caller error on the field it belongs to', () => {
    render(
      <DateRangePicker
        value={{ start: '2026-12-04', end: '2026-12-01' }}
        onChange={() => {}}
        endError="The end date cannot be before the start date."
        today={TODAY}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('The end date cannot be before the start')
  })

  it('disables both fields and both calendar buttons when the form is read-only', () => {
    render(
      <DateRangePicker value={{ start: '', end: '' }} onChange={() => {}} disabled today={TODAY} />,
    )
    expect(startInput()).toBeDisabled()
    expect(screen.getByRole('button', { name: /Start date — open calendar/ })).toBeDisabled()
  })
})

describe('DateRangePicker — ARIA structure', () => {
  it('renders each month as a labelled grid of gridcells', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '2026-12-11' }} />)
    openStart()
    const [december] = grid()
    expect(december).toHaveAccessibleName('December 2026')
    expect(within(december).getAllByRole('gridcell')).toHaveLength(42)
    expect(within(december).getAllByRole('row').length).toBeGreaterThanOrEqual(6)
  })

  it('marks the selected edges with aria-selected on their gridcell', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '2026-12-11' }} />)
    openStart()
    expect(day('2026-12-04').closest('td')).toHaveAttribute('aria-selected', 'true')
    expect(day('2026-12-05').closest('td')).toHaveAttribute('aria-selected', 'false')
  })

  it('gives the whole month one tab stop via a roving tabindex', () => {
    render(<Harness initial={{ start: '2026-12-04', end: '' }} />)
    openStart()
    const [december] = grid()
    const focusable = within(december)
      .getAllByRole('button')
      .filter((node) => node.getAttribute('tabindex') === '0')
    expect(focusable).toHaveLength(1)
    expect(focusable[0]).toHaveAccessibleName(expect.stringContaining('4 December 2026') as never)
  })

  it('announces the selection politely as the range is built', () => {
    render(<Harness />)
    openStart()
    const status = screen.getAllByRole('status').at(-1)!
    expect(status).toHaveAttribute('aria-live', 'polite')
    fireEvent.click(day('2026-08-04'))
    expect(screen.getByText(/Start 4 Aug 2026 selected\. Now pick the end date\./)).toBeInTheDocument()
  })

  it('names today for assistive tech without relying on the ring alone', () => {
    render(<Harness />)
    openStart()
    expect(day('2026-08-11')).toHaveAttribute('aria-current', 'date')
  })
})
