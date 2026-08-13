/**
 * The Google-place profile (`design.md` > "What a clicked place shows"). Two things matter:
 * it shows what Google would show, and it never invents what Google did not return — a place
 * with no phone must render no phone row, not an empty one.
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { PlaceProfilePanel } from './PlaceProfilePanel'
import type { PlaceDetails } from './placesClient'

function details(overrides: Partial<PlaceDetails> = {}): PlaceDetails {
  return {
    placeId: 'place-1',
    name: 'Spitalfields Market',
    address: '65 Brushfield St, London E1 6AA, UK',
    lat: 51.5192,
    lng: -0.0757,
    photoUrls: [],
    rating: 4.5,
    ratingCount: 34692,
    openingHoursText: ['Monday: 10:00 – 20:00', 'Tuesday: 10:00 – 20:00'],
    openNow: true,
    types: ['tourist_attraction', 'point_of_interest'],
    website: 'https://www.spitalfields.co.uk/shop',
    editorialSummary: 'Lively market with independent vendors.',
    phone: '020 7377 1496',
    ...overrides,
  }
}

const noop = () => {}

describe('PlaceProfilePanel', () => {
  it('shows the facts Google shows', () => {
    render(
      <PlaceProfilePanel place={details()} loading={false} error={null} canAdd onAdd={noop} onClose={noop} />,
    )

    expect(screen.getByRole('heading', { name: 'Spitalfields Market' })).toBeInTheDocument()
    expect(screen.getByText('65 Brushfield St, London E1 6AA, UK')).toBeInTheDocument()
    expect(screen.getByText('Lively market with independent vendors.')).toBeInTheDocument()
    expect(screen.getByText('Monday: 10:00 – 20:00')).toBeInTheDocument()
    expect(screen.getByText('Open now')).toBeInTheDocument()
    // The rating carries its sample size, and the host stands in for a URL nobody reads.
    expect(screen.getByText(/4\.5/)).toBeInTheDocument()
    expect(screen.getByText(/34,692/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'spitalfields.co.uk' })).toHaveAttribute(
      'href',
      'https://www.spitalfields.co.uk/shop',
    )
    expect(screen.getByRole('link', { name: '020 7377 1496' })).toHaveAttribute('href', 'tel:02073771496')
  })

  it('omits rows Google had no answer for', () => {
    render(
      <PlaceProfilePanel
        place={details({ phone: null, website: null, openingHoursText: null, rating: null, openNow: null })}
        loading={false}
        error={null}
        canAdd
        onAdd={noop}
        onClose={noop}
      />,
    )

    expect(screen.queryByText('Phone')).not.toBeInTheDocument()
    expect(screen.queryByText('Website')).not.toBeInTheDocument()
    expect(screen.queryByText('Opening hours')).not.toBeInTheDocument()
    expect(screen.queryByText('Open now')).not.toBeInTheDocument()
    // …but the place itself still reads as a place.
    expect(screen.getByRole('heading', { name: 'Spitalfields Market' })).toBeInTheDocument()
  })

  it('hands the place to the create flow, carrying only what may be persisted', () => {
    const onAdd = vi.fn()
    render(
      <PlaceProfilePanel place={details()} loading={false} error={null} canAdd onAdd={onAdd} onClose={noop} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Add as suggestion' }))

    // The ToS invariant, asserted at the one boundary where Google's data could leak into
    // ours: no rating, hours, phone, photos or summary travel with the seed.
    expect(onAdd).toHaveBeenCalledWith({
      placeId: 'place-1',
      name: 'Spitalfields Market',
      address: '65 Brushfield St, London E1 6AA, UK',
      position: { lat: 51.5192, lng: -0.0757 },
      types: ['tourist_attraction', 'point_of_interest'],
    })
  })

  it('cannot add during a read-only stage', () => {
    render(
      <PlaceProfilePanel
        place={details()}
        loading={false}
        error={null}
        canAdd={false}
        onAdd={noop}
        onClose={noop}
      />,
    )
    expect(screen.getByRole('button', { name: 'Add as suggestion' })).toBeDisabled()
  })

  it('says so when the lookup failed, rather than showing an empty shell', () => {
    render(
      <PlaceProfilePanel
        place={null}
        loading={false}
        error="That place could not be loaded."
        canAdd
        onAdd={noop}
        onClose={noop}
      />,
    )
    expect(screen.getByText('That place could not be loaded.')).toBeInTheDocument()
  })
})
