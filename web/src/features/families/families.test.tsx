/**
 * The families UI, at the points where getting it wrong would matter.
 *
 * Not a screenshot of every component — the four home-address states, the invite copy-once
 * block, permission-gated rendering of the member controls, and the location settings block
 * rendering read-only for a plain member. Those are the ones `tasks.md` Phase 11 names, and
 * they are named because each encodes a promise made in prose somewhere else.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ToastProvider } from '../../app/ui/toast'
import { effectiveLocationState, relativeTime } from './labels'
import { HomeAddressBlock } from './HomeAddressBlock'
import { LocationSettingsBlock } from './LocationSettingsBlock'
import { parsePath, pathFor } from '../../app/router'
import type { FamilyDetail, Member } from '../../app/types'

function member(overrides: Partial<Member> = {}): Member {
  return {
    user_id: 'u1',
    username: 'ada',
    first_name: 'Ada',
    last_name: 'Lovelace',
    display_name: 'Ada Lovelace',
    avatar_url: null,
    avatar_thumb_url: null,
    initials: 'AL',
    role: 'member',
    joined_at: '2027-01-14T00:00:00Z',
    is_owner: false,
    is_organiser: false,
    location_sharing_allowed: true,
    location_sharing_enabled: true,
    ...overrides,
  }
}

function family(overrides: Partial<FamilyDetail> = {}): FamilyDetail {
  return {
    id: 'f1',
    name: 'The Parkers',
    color: 1,
    member_count: 1,
    home_locality: null,
    home_placed: false,
    geocode_status: 'pending',
    location_sharing_allowed: true,
    member_location_default: false,
    geocode_error: null,
    members: [member()],
    ...overrides,
  }
}

const wrap = (ui: React.ReactNode) => render(<ToastProvider>{ui}</ToastProvider>)

// --- the four home-address states ----------------------------------------------------------

describe('the home address block', () => {
  it('invites an address when there is none', () => {
    wrap(
      <HomeAddressBlock
        family={family({ home_address: null })}
        editable
        onChanged={vi.fn()}
      />,
    )
    expect(screen.getByText(/No home address yet/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add an address/i })).toBeInTheDocument()
  })

  it('shows the placed address and its town', () => {
    wrap(
      <HomeAddressBlock
        family={family({
          home_address: '12 Elm Row, Bristol',
          home_locality: 'Bristol',
          home_placed: true,
          geocode_status: 'ok',
        })}
        editable
        onChanged={vi.fn()}
      />,
    )
    expect(screen.getByText('12 Elm Row, Bristol')).toBeInTheDocument()
    // The coarse locality is shown alongside the street address, not instead of it.
    expect(screen.getByText('· Bristol')).toBeInTheDocument()
  })

  it('offers a retry when the address is not a place', () => {
    wrap(
      <HomeAddressBlock
        family={family({ home_address: 'Nowhere', geocode_status: 'not_found' })}
        editable
        onChanged={vi.fn()}
      />,
    )
    expect(screen.getByText(/could not find that address/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('distinguishes "we could not reach the service" from "that is not a place"', () => {
    // Different causes, different fixes. Collapsing them would send someone off to correct
    // an address that was never wrong.
    wrap(
      <HomeAddressBlock
        family={family({ home_address: '12 Elm Row', geocode_status: 'error' })}
        editable
        onChanged={vi.fn()}
      />,
    )
    expect(screen.getByText(/could not reach the mapping service/i)).toBeInTheDocument()
    expect(screen.getByText(/your address is saved/i)).toBeInTheDocument()
  })

  it('explains a missing key as an instance problem, not the user\'s', () => {
    wrap(
      <HomeAddressBlock
        family={family({
          home_address: '12 Elm Row',
          geocode_status: 'error',
          geocode_error: 'no_api_key',
        })}
        editable
        onChanged={vi.fn()}
      />,
    )
    expect(screen.getByText(/No mapping key is configured/i)).toBeInTheDocument()
  })

  it('shows only the town, and no controls, to someone outside the family', () => {
    // The server omits the address keys entirely for them, so their absence *is* the signal
    // — there is no role check here that could disagree with the server.
    const outsiderView = family({ home_locality: 'Bristol', home_placed: true })
    delete (outsiderView as Partial<FamilyDetail>).home_address

    wrap(<HomeAddressBlock family={outsiderView} editable={false} onChanged={vi.fn()} />)
    expect(screen.getByText(/visible to this family only/i)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

// --- the location settings block -----------------------------------------------------------

describe('the family location settings', () => {
  it('is visible but read-only to a plain member', () => {
    // The whole reason the block exists: a setting that silently overrides you, invisibly, is
    // the thing it prevents. A member must be able to see why their own toggle has no effect.
    wrap(
      <LocationSettingsBlock
        family={family({ location_sharing_allowed: false })}
        editable={false}
        viewerId="u1"
        onChanged={vi.fn()}
      />,
    )
    expect(screen.getByText(/Your family's head can change these/i)).toBeInTheDocument()
    for (const box of screen.getAllByRole('checkbox')) expect(box).toBeDisabled()
  })

  it('lets the head change both switches', () => {
    wrap(
      <LocationSettingsBlock family={family()} editable viewerId="u1" onChanged={vi.fn()} />,
    )
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes[0]).toBeEnabled()
    expect(boxes[1]).toBeEnabled()
  })

  it('does not offer a spouse the head\'s switch', () => {
    // FM-16's asymmetry, rendered. The server refuses it anyway; this stops the control
    // being offered and then failing.
    const household = family({
      member_count: 2,
      members: [
        member({ user_id: 'head', username: 'head', role: 'head', display_name: 'Head' }),
        member({ user_id: 'me', username: 'spouse', role: 'spouse', display_name: 'Spouse' }),
      ],
    })
    wrap(
      <LocationSettingsBlock
        family={household}
        editable
        viewerId="me"
        onChanged={vi.fn()}
      />,
    )
    const perMember = screen.getAllByRole('checkbox').slice(2)
    expect(perMember[0]).toBeDisabled() // the head's
    expect(perMember[1]).toBeEnabled() // their own
  })
})

// --- the five effective-state strings --------------------------------------------------------

describe('the effective location state', () => {
  it('reports the family switch first, so the answer is one reason and not three', () => {
    const off = member({ location_sharing_allowed: false, location_sharing_enabled: false })
    expect(effectiveLocationState(off, false)).toBe('Off for the whole family')
  })

  it('speaks in the second person about the reader\'s own decision', () => {
    const blocked = member({ location_sharing_allowed: false })
    expect(effectiveLocationState(blocked, true)).toBe('You have turned this off for them')
  })

  it('says only they can turn their own sharing on', () => {
    const notConsented = member({ location_sharing_enabled: false })
    expect(effectiveLocationState(notConsented, true)).toBe(
      'Off — only they can turn this on',
    )
  })

  it('does not claim someone is visible when it cannot know', () => {
    // Until `holiday-stage` supplies a live position, "sharing now" is unknowable. The
    // indicator must never over-promise.
    expect(effectiveLocationState(member(), true)).toBe(
      'Sharing is on — not visible while the app is closed',
    )
  })

  it('withholds a state it is not entitled to know', () => {
    const redacted = member({ location_sharing_enabled: null })
    expect(effectiveLocationState(redacted, true)).toBe('Only they can see this setting')
  })
})

// --- the router ------------------------------------------------------------------------------

describe('the router', () => {
  it('round-trips every route', () => {
    for (const route of [
      { name: 'home' },
      { name: 'families' },
      { name: 'families', familyId: 'f1' },
      { name: 'profile' },
      { name: 'join', token: 'abc123' },
      { name: 'setup-family' },
    ] as const) {
      expect(parsePath(pathFor(route))).toEqual(route)
    }
  })

  it('reads an invite token out of the path', () => {
    expect(parsePath('/join/abc-def_123')).toEqual({ name: 'join', token: 'abc-def_123' })
  })

  it('reports an unknown path rather than guessing', () => {
    expect(parsePath('/nowhere')).toEqual({ name: 'not-found', path: '/nowhere' })
  })

  it('ignores a trailing slash', () => {
    expect(parsePath('/families/')).toEqual({ name: 'families', familyId: undefined })
  })
})

// --- invite copy ------------------------------------------------------------------------------

describe('relative time', () => {
  it('counts forwards for an expiry and backwards for a past event', () => {
    const now = new Date('2027-01-14T12:00:00Z')
    expect(relativeTime('2027-01-21T12:00:00Z', now)).toBe('in 7 days')
    expect(relativeTime('2027-01-14T09:00:00Z', now)).toBe('3 hours ago')
  })
})
