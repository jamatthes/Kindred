/**
 * The keyboard map, tested key by key.
 *
 * Phase 11 promises a complete one, and "complete" is only meaningful if each key is pinned:
 * a picker that loses PageUp when someone refactors the switch is a picker a keyboard user
 * cannot get out of the current month with.
 */

import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { CalendarSurface } from './CalendarSurface'
import type { IsoDate } from './calendar'

const TODAY = '2026-08-11'

function Harness({
  selected = '2026-08-11',
  min = null,
  max = null,
  months = 1,
  onSelect = () => {},
  onClose = () => {},
}: {
  selected?: IsoDate | null
  min?: IsoDate | null
  max?: IsoDate | null
  months?: 1 | 2
  onSelect?: (date: IsoDate) => void
  onClose?: () => void
}) {
  const [month, setMonth] = useState<IsoDate>('2026-08-01')
  return (
    <CalendarSurface
      visibleMonth={month}
      onVisibleMonthChange={setMonth}
      selected={selected}
      min={min}
      max={max}
      months={months}
      onSelect={onSelect}
      onClose={onClose}
      today={TODAY}
    />
  )
}

/** The one cell in the tab order — the caret, by definition. */
function caret(): HTMLElement {
  const cells = [...document.querySelectorAll<HTMLElement>('[data-date]')].filter(
    (cell) => cell.getAttribute('tabindex') === '0',
  )
  expect(cells).toHaveLength(1)
  return cells[0]
}

function press(key: string, init: Partial<KeyboardEventInit> = {}) {
  fireEvent.keyDown(caret(), { key, ...init })
}

describe('CalendarSurface — keyboard', () => {
  it('opens with the caret on the selected day and DOM focus in the grid', () => {
    render(<Harness />)
    expect(caret()).toHaveAttribute('data-date', '2026-08-11')
    expect(document.activeElement).toBe(caret())
  })

  it('moves a day with ← and →', () => {
    render(<Harness />)
    press('ArrowRight')
    expect(caret()).toHaveAttribute('data-date', '2026-08-12')
    press('ArrowLeft')
    press('ArrowLeft')
    expect(caret()).toHaveAttribute('data-date', '2026-08-10')
  })

  it('moves a week with ↑ and ↓', () => {
    render(<Harness />)
    press('ArrowDown')
    expect(caret()).toHaveAttribute('data-date', '2026-08-18')
    press('ArrowUp')
    press('ArrowUp')
    expect(caret()).toHaveAttribute('data-date', '2026-08-04')
  })

  it('jumps to the ends of the week with Home and End', () => {
    render(<Harness />)
    press('Home') // 11 Aug 2026 is a Tuesday; the week starts Monday the 10th
    expect(caret()).toHaveAttribute('data-date', '2026-08-10')
    press('End')
    expect(caret()).toHaveAttribute('data-date', '2026-08-16')
  })

  it('moves a month with PageUp and PageDown, and pages the visible month with it', () => {
    render(<Harness />)
    press('PageDown')
    expect(caret()).toHaveAttribute('data-date', '2026-09-11')
    expect(screen.getByText('September 2026')).toBeInTheDocument()
    press('PageUp')
    press('PageUp')
    expect(caret()).toHaveAttribute('data-date', '2026-07-11')
    expect(screen.getByText('July 2026')).toBeInTheDocument()
  })

  it('moves a year with Shift+PageUp and Shift+PageDown', () => {
    render(<Harness />)
    press('PageDown', { shiftKey: true })
    expect(caret()).toHaveAttribute('data-date', '2027-08-11')
    expect(screen.getByText('August 2027')).toBeInTheDocument()
    press('PageUp', { shiftKey: true })
    press('PageUp', { shiftKey: true })
    expect(caret()).toHaveAttribute('data-date', '2025-08-11')
  })

  it('selects the caret with Enter and with Space', () => {
    const chosen: IsoDate[] = []
    render(<Harness onSelect={(date) => chosen.push(date)} />)
    press('ArrowRight')
    press('Enter')
    press('ArrowRight')
    press(' ')
    expect(chosen).toEqual(['2026-08-12', '2026-08-13'])
  })

  it('closes on Escape', () => {
    let closed = 0
    render(<Harness onClose={() => (closed += 1)} />)
    press('Escape')
    expect(closed).toBe(1)
  })

  it('parks the caret at the wall rather than appearing to do nothing', () => {
    render(<Harness min="2026-08-10" max="2026-08-20" />)
    press('ArrowLeft')
    expect(caret()).toHaveAttribute('data-date', '2026-08-10')
    press('ArrowLeft')
    expect(caret()).toHaveAttribute('data-date', '2026-08-10')
    press('PageDown')
    expect(caret()).toHaveAttribute('data-date', '2026-08-20')
  })

  it('refuses to select a day outside the allowed range', () => {
    const chosen: IsoDate[] = []
    render(<Harness min="2026-08-11" onSelect={(date) => chosen.push(date)} />)
    press('ArrowLeft') // clamped back onto the 11th
    press('Enter')
    expect(chosen).toEqual(['2026-08-11'])
  })

  it('paints a keyboard preview so the caret is the range edge too', () => {
    render(
      <CalendarSurface
        visibleMonth="2026-08-01"
        onVisibleMonthChange={() => {}}
        selected={null}
        rangeFrom="2026-08-04"
        rangeTo={null}
        onSelect={() => {}}
        today={TODAY}
      />,
    )
    // Three days out from the 4th, so there are days *between* the edge and the caret.
    fireEvent.keyDown(caret(), { key: 'ArrowRight' })
    fireEvent.keyDown(caret(), { key: 'ArrowRight' })
    fireEvent.keyDown(caret(), { key: 'ArrowRight' })
    const painted = [...document.querySelectorAll<HTMLElement>('[data-date]')]
      .filter((cell) => cell.className.includes('preview'))
      .map((cell) => cell.dataset.date)
    expect(painted).toEqual(['2026-08-05', '2026-08-06'])
  })
})

describe('CalendarSurface — structure and jump controls', () => {
  it('is a grid of rows and gridcells with a labelled caption', () => {
    render(<Harness />)
    const table = screen.getByRole('grid')
    expect(table).toHaveAccessibleName('August 2026')
    expect(within(table).getAllByRole('row')).toHaveLength(7) // 6 weeks + the header row
    expect(within(table).getAllByRole('gridcell')).toHaveLength(42)
    expect(within(table).getAllByRole('columnheader')).toHaveLength(7)
  })

  it('jumps whole months and years from two selects, not from chevron mashing', () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Year'), { target: { value: '2028' } })
    expect(screen.getByText('August 2028')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Month'), { target: { value: '11' } })
    expect(screen.getByText('December 2028')).toBeInTheDocument()
  })

  it('steps a month at a time from the chevrons', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'Next month' }))
    expect(screen.getByText('September 2026')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Previous month' }))
    fireEvent.click(screen.getByRole('button', { name: 'Previous month' }))
    expect(screen.getByText('July 2026')).toBeInTheDocument()
  })

  it('names every weekday column for a screen reader, not just its abbreviation', () => {
    render(<Harness />)
    expect(screen.getByText('Monday')).toBeInTheDocument()
    expect(screen.getByText('Sunday')).toBeInTheDocument()
  })
})
