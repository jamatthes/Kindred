/**
 * Our replacement for Google's own POI info window (requirements S3b).
 *
 * The card exists to carry one action Google's window cannot, so the tests are about the
 * three states a click can land in — resolving, failed, resolved — and about the promise in
 * `design.md`'s hard invariant: dismissing the card writes nothing, it only stops showing
 * details that were never ours to keep.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PlacePreviewCard } from './PlacePreviewCard'
import type { PlaceSeed } from './CreateSuggestionForm'

const place: PlaceSeed = {
  placeId: 'place-1',
  name: 'The Minack Theatre',
  address: 'Porthcurno, Penzance',
  position: { lat: 50.04, lng: -5.65 },
  types: ['tourist_attraction'],
}

describe('PlacePreviewCard', () => {
  it('shows the place and hands the whole seed back on "Add as suggestion"', () => {
    const onAdd = vi.fn()
    render(<PlacePreviewCard place={place} loading={false} error={null} canAdd onAdd={onAdd} onClose={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'The Minack Theatre' })).toBeInTheDocument()
    expect(screen.getByText('Porthcurno, Penzance')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add as suggestion' }))
    // The same object, not a re-derived one: the parent already paid for Place Details and
    // the create form is seeded from this exact result rather than a second lookup.
    expect(onAdd).toHaveBeenCalledWith(place)
  })

  it('waits without claiming anything while Place Details resolves', () => {
    render(<PlacePreviewCard place={null} loading error={null} canAdd onAdd={vi.fn()} onClose={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Add as suggestion' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
  })

  it('says so when the lookup failed, rather than showing an empty card', () => {
    render(
      <PlacePreviewCard
        place={null}
        loading={false}
        error="That place could not be loaded."
        canAdd
        onAdd={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText('That place could not be loaded.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add as suggestion' })).not.toBeInTheDocument()
  })

  it('disables the add action when the stage forbids mutation, and still closes', () => {
    const onClose = vi.fn()
    render(
      <PlacePreviewCard place={place} loading={false} error={null} canAdd={false} onAdd={vi.fn()} onClose={onClose} />,
    )
    expect(screen.getByRole('button', { name: 'Add as suggestion' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('links out to Google Maps by URL — no API call, no key, nothing persisted', () => {
    render(<PlacePreviewCard place={place} loading={false} error={null} canAdd onAdd={vi.fn()} onClose={vi.fn()} />)
    const link = screen.getByRole('link', { name: 'Open in Google Maps' })
    expect(link).toHaveAttribute('href', expect.stringContaining('query_place_id=place-1'))
    expect(link).toHaveAttribute('target', '_blank')
  })
})
