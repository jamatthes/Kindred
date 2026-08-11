import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { DatePicker } from './DatePicker'
import type { IsoDate } from './calendar'

const TODAY = '2026-08-11'
const TRIP = { start: '2026-08-10', end: '2026-08-16' }

function Harness(props: Partial<Parameters<typeof DatePicker>[0]> = {}) {
  const [value, setValue] = useState<IsoDate | ''>('')
  return (
    <DatePicker label="Day" value={value} onChange={setValue} today={TODAY} {...props} />
  )
}

const field = () => screen.getByLabelText('Day', { selector: 'input' })

describe('DatePicker — trip-aware day strip', () => {
  it('renders the trip’s days as the primary control', () => {
    render(<Harness trip={TRIP} />)
    const strip = screen.getByRole('group', { name: /days of the trip/ })
    expect(strip.querySelectorAll('.k-picker-strip__day')).toHaveLength(7)
  })

  it('fills the field from one tap on a day', () => {
    render(<Harness trip={TRIP} />)
    fireEvent.click(screen.getByRole('button', { name: /12 August 2026/ }))
    expect(field()).toHaveValue('2026-08-12')
    expect(screen.getByRole('button', { name: /12 August 2026/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('keeps the whole calendar one gesture away', () => {
    render(<Harness trip={TRIP} />)
    expect(screen.queryByRole('grid')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Any date' }))
    expect(screen.getByRole('grid')).toBeInTheDocument()
  })

  it('bounds the calendar to the trip unless the caller opens it up', () => {
    const { unmount } = render(<Harness trip={TRIP} />)
    expect(field()).toHaveAttribute('min', TRIP.start)
    expect(field()).toHaveAttribute('max', TRIP.end)
    unmount()
    render(<Harness trip={TRIP} allowOutsideTrip />)
    expect(field()).not.toHaveAttribute('min')
  })

  it('drops the strip for a span too long to scan and leaves the calendar', () => {
    render(<Harness trip={{ start: '2026-08-01', end: '2026-10-01' }} />)
    expect(screen.queryByRole('group', { name: /days of the trip/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open calendar/ })).toBeInTheDocument()
  })

  it('is the plain field and calendar with no trip at all', () => {
    render(<Harness />)
    expect(screen.queryByRole('group', { name: /days of the trip/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /open calendar/ }))
    expect(screen.getByRole('grid')).toHaveAccessibleName('August 2026')
  })
})

describe('DatePicker — single selection', () => {
  it('picks a date from the calendar and closes', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: /open calendar/ }))
    fireEvent.click(document.querySelector('[data-date="2026-08-20"]')!)
    expect(field()).toHaveValue('2026-08-20')
    expect(screen.queryByRole('grid')).not.toBeInTheDocument()
  })

  it('opens the calendar at the chosen date’s month, not at today', () => {
    render(<Harness />)
    // A value four months out, typed rather than picked.
    fireEvent.change(field(), { target: { value: '2026-12-04' } })
    fireEvent.click(screen.getByRole('button', { name: /open calendar/ }))
    expect(screen.getByText('December 2026')).toBeInTheDocument()
  })

  it('shows a caller error and marks the field invalid', () => {
    render(<Harness error="Pick a day inside the trip." />)
    expect(screen.getByRole('alert')).toHaveTextContent('Pick a day inside the trip.')
    expect(field()).toHaveAttribute('aria-invalid', 'true')
  })

  it('disables the strip and the calendar button when disabled', () => {
    render(<Harness trip={TRIP} disabled />)
    expect(field()).toBeDisabled()
    expect(screen.getByRole('button', { name: /open calendar/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /12 August 2026/ })).toBeDisabled()
  })
})
