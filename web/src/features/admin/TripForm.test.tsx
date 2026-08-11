/**
 * The trip-dates swap (design-system Phase 11).
 *
 * The form is the only shipped consumer of the pickers, and the reason it was swapped is a
 * bug someone hit in it. These tests are that bug, at the console level, plus the promise
 * that came with the swap: the PATCH body did not change.
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { TripForm } from './TripForm'
import { adminApi } from './api'
import type { TripAdmin } from '../../app/types'

const trip = (overrides: Partial<TripAdmin> = {}): TripAdmin => ({
  id: 't1',
  name: 'Cornwall · July 2027',
  stage: 'planning',
  start_date: null,
  end_date: null,
  timezone: 'Europe/London',
  owner_user_id: 'u1',
  can_advance_to: 'holiday',
  can_revert_to: null,
  blockers: [],
  setup_complete: true,
  ...overrides,
})

const startInput = () => screen.getByLabelText('Start date', { selector: 'input' })
const endInput = () => screen.getByLabelText('End date', { selector: 'input' })

describe('TripForm — the dates are the DateRangePicker now', () => {
  it('opens the end calendar at the start’s month rather than at today', () => {
    render(<TripForm trip={trip({ start_date: '2027-12-04' })} submitLabel="Save" onSaved={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /End date — open calendar/ }))
    expect(screen.getByText('December 2027')).toBeInTheDocument()
    expect(document.querySelector('[data-date="2027-12-03"]')).toHaveAttribute(
      'aria-disabled',
      'true',
    )
  })

  it('offers the trip-shaped quick picks, not an analytics set', () => {
    render(<TripForm trip={trip()} submitLabel="Save" onSaved={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /Start date — open calendar/ }))
    const picks = screen.getByRole('group', { name: 'Quick picks' })
    expect(picks).toHaveTextContent('This weekend')
    expect(picks).toHaveTextContent('A week')
    expect(picks).toHaveTextContent('A fortnight')
    expect(picks).not.toHaveTextContent('Last 30 days')
  })

  it('sends the same two ISO fields it always did', async () => {
    const patch = vi
      .spyOn(adminApi, 'patchTrip')
      .mockResolvedValue(trip({ start_date: '2027-07-17', end_date: '2027-07-24' }))
    render(<TripForm trip={trip()} submitLabel="Save" onSaved={() => {}} />)

    fireEvent.change(startInput(), { target: { value: '2027-07-17' } })
    fireEvent.change(endInput(), { target: { value: '2027-07-24' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith({ start_date: '2027-07-17', end_date: '2027-07-24' }),
    )
  })

  it('clears an end that a new start invalidates, and says so', () => {
    render(
      <TripForm
        trip={trip({ start_date: '2027-07-17', end_date: '2027-07-24' })}
        submitLabel="Save"
        onSaved={() => {}}
      />,
    )
    fireEvent.change(startInput(), { target: { value: '2027-08-01' } })
    expect(endInput()).toHaveValue('')
    expect(screen.getByRole('status')).toHaveTextContent(/end date has been cleared/i)
  })

  it('still treats undecided dates as normal in Planning', () => {
    render(<TripForm trip={trip()} submitLabel="Save" onSaved={() => {}} />)
    expect(screen.getByText('Dates not decided yet.')).toBeInTheDocument()
    expect(screen.getByText('No dates chosen yet')).toBeInTheDocument()
  })

  it('says the dates are optional on the setup screen', () => {
    render(
      <TripForm trip={trip()} submitLabel="Create trip" datesOptionalHint onSaved={() => {}} />,
    )
    expect(screen.getByText('You can decide this later.')).toBeInTheDocument()
  })

  it('is inert in the End stage', () => {
    render(
      <TripForm
        trip={trip({ start_date: '2027-07-17', end_date: '2027-07-24' })}
        submitLabel="Save"
        onSaved={() => {}}
        readOnly
      />,
    )
    expect(startInput()).toBeDisabled()
    expect(screen.getByRole('button', { name: /Start date — open calendar/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  })
})
