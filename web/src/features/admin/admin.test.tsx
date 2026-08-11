/**
 * Phase 11 — the console's client-side rules.
 *
 * These test the things a server test cannot: that the confirm dialog says what will happen
 * in the words the design document chose, that a blocked action explains itself rather than
 * being mysteriously grey, that a status is legible without colour, and that the two
 * role-gated surfaces are absent for the roles that must not see them.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import App from '../../App'
import { GoogleSection } from './GoogleSection'
import { StageSection } from './StageSection'
import type {
  AdminMember,
  GoogleStatus,
  Organiser,
  TripAdmin,
  User,
} from '../../app/types'

const trip = (overrides: Partial<TripAdmin> = {}): TripAdmin => ({
  id: 't1',
  name: 'Cornwall · July 2027',
  stage: 'planning',
  start_date: '2027-07-17',
  end_date: '2027-07-24',
  timezone: 'Europe/London',
  owner_user_id: 'u1',
  can_advance_to: 'holiday',
  can_revert_to: null,
  blockers: [],
  setup_complete: true,
  ...overrides,
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// --- the stage section ---------------------------------------------------------------------

describe('the stage confirms', () => {
  it('names the consequences of starting the holiday, and labels the button with the action', () => {
    render(<StageSection trip={trip()} history={[]} onChanged={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: 'Start the holiday' }))

    const dialog = screen.getByRole('alertdialog')
    expect(within(dialog).getByText('Voting and suggestions stay open.')).toBeInTheDocument()
    expect(
      within(dialog).getByText('The app switches to the now/next view on phones.'),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('Check-ins become available.')).toBeInTheDocument()
    // Never a bare "OK": the button says what pressing it does.
    expect(within(dialog).getByRole('button', { name: 'Start the holiday' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'OK' })).not.toBeInTheDocument()
  })

  it('warns that freezing the trip takes everything away, and that it is reversible', () => {
    render(
      <StageSection
        trip={trip({ stage: 'holiday', can_advance_to: 'end', can_revert_to: 'planning' })}
        history={[]}
        onChanged={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Freeze the trip' }))

    const dialog = screen.getByRole('alertdialog')
    expect(
      within(dialog).getByText('Everyone loses the ability to change anything.'),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText('You can undo this from here if it was a mistake.'),
    ).toBeInTheDocument()
  })

  it('disables the forward action and says why, in words', () => {
    render(
      <StageSection
        trip={trip({
          start_date: null,
          end_date: null,
          can_advance_to: null,
          blockers: ['missing_dates'],
        })}
        history={[]}
        onChanged={() => {}}
      />,
    )

    expect(screen.getByRole('button', { name: 'Start the holiday' })).toBeDisabled()
    // The machine-readable code never reaches the screen; the reason does.
    expect(screen.getByText(/Set the start and end dates first/)).toBeInTheDocument()
    expect(screen.queryByText(/missing_dates/)).not.toBeInTheDocument()
  })

  it('offers the backward move as a correction, separately from the forward one', () => {
    render(
      <StageSection
        trip={trip({ stage: 'end', can_advance_to: null, can_revert_to: 'holiday' })}
        history={[]}
        onChanged={() => {}}
      />,
    )

    expect(screen.getByText('This trip is finished. There is nowhere forward.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go back to Holiday' })).toBeInTheDocument()
  })

  it('shows who moved the stage, and marks a correction as one', () => {
    render(
      <StageSection
        trip={trip({ stage: 'holiday', can_advance_to: 'end', can_revert_to: 'planning' })}
        history={[
          {
            from_stage: 'end',
            to_stage: 'holiday',
            direction: 'backward',
            changed_by: { user_id: 'u1', display_name: 'Jacob Parker' },
            created_at: '2027-07-20T10:00:00Z',
          },
        ]}
        onChanged={() => {}}
      />,
    )

    expect(screen.getByText('Jacob Parker')).toBeInTheDocument()
    expect(screen.getByText('correction')).toBeInTheDocument()
  })
})

// --- the Google section ----------------------------------------------------------------------

describe('the Google status table', () => {
  const status = (rows: GoogleStatus['apis']): GoogleStatus => ({
    checked_at: '2027-07-01T09:00:00Z',
    checked_by: 'u1',
    browser_key_configured: true,
    server_key_configured: true,
    apis: rows,
  })

  it('renders every status as a word, not as a colour', () => {
    render(
      <GoogleSection
        onChecked={() => {}}
        status={status([
          { name: 'Places', key_type: 'server', status: 'ok', detail: 'OK', hint: null },
          {
            name: 'Geocoding',
            key_type: 'server',
            status: 'denied',
            detail: 'REQUEST_DENIED',
            hint: 'The API may not be enabled in your Google Cloud project.',
          },
          {
            name: 'Distance Matrix',
            key_type: 'server',
            status: 'quota',
            detail: 'OVER_QUERY_LIMIT',
            hint: 'The daily cap has been reached.',
          },
          {
            name: 'Directions',
            key_type: 'server',
            status: 'unreachable',
            detail: 'timeout',
            hint: 'The server could not reach Google.',
          },
        ])}
      />,
    )

    for (const word of ['OK', 'Denied', 'Quota', 'Unreachable']) {
      expect(screen.getByText(word)).toBeInTheDocument()
    }
    // And each failure explains its usual cause inline.
    expect(
      screen.getByText('The API may not be enabled in your Google Cloud project.'),
    ).toBeInTheDocument()
  })

  it('says Maps JS cannot be checked rather than implying it was', () => {
    render(
      <GoogleSection
        onChecked={() => {}}
        status={status([
          {
            name: 'Maps JavaScript',
            key_type: 'browser',
            status: 'configured',
            detail: null,
            hint: null,
          },
        ])}
      />,
    )

    expect(screen.getByText('Configured')).toBeInTheDocument()
    expect(
      screen.getByText('It cannot be verified from the server — it loads in the browser.'),
    ).toBeInTheDocument()
  })

  it('has never been checked, and says so instead of showing a blank area', () => {
    render(
      <GoogleSection
        onChecked={() => {}}
        status={{
          checked_at: null,
          checked_by: null,
          browser_key_configured: false,
          server_key_configured: false,
          apis: [
            {
              name: 'Places',
              key_type: 'server',
              status: 'unchecked',
              detail: 'no_api_key',
              hint: 'No key is configured in `.env`.',
            },
          ],
        }}
      />,
    )

    expect(screen.getByText(/It has never been run/)).toBeInTheDocument()
    expect(screen.getByText('Not checked')).toBeInTheDocument()
  })
})

// --- who sees the console --------------------------------------------------------------------

const baseUser: User = {
  id: 'u9',
  username: 'member',
  first_name: 'Plain',
  last_name: 'Member',
  display_name: 'Plain Member',
  avatar_url: null,
  avatar_thumb_url: null,
  initials: 'PM',
  is_platform_admin: false,
  is_owner: false,
  is_organiser: false,
  must_change_password: false,
  next_step: 'app',
  theme_pref: 'light',
  locale: 'en-GB',
  family: { id: 'f1', name: 'The Jiangs', color: 5, role: 'member' },
  trip: {
    id: 't1',
    name: 'Cornwall · July 2027',
    stage: 'planning',
    start_date: '2027-07-17',
    end_date: '2027-07-24',
    timezone: 'Europe/London',
  },
}

function stubApp(user: User, extra: Record<string, unknown> = {}) {
  window.history.pushState({}, '', '/admin')
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string) => {
      const url = String(input)
      const body = (payload: unknown, status = 200) =>
        Promise.resolve(new Response(JSON.stringify(payload), { status }))
      if (url.endsWith('/auth/me')) return body(user)
      if (url.endsWith('/settings')) {
        return body({ instance_name: 'Kindred', registration_open: false, invite_only: true })
      }
      if (url.endsWith('/presence')) return body({ online_user_ids: [] })
      if (url.includes('/admin/trip/stage-history')) return body([])
      if (url.includes('/admin/trip')) return body(trip())
      if (url.includes('/admin/category-settings')) return body([])
      if (url.includes('/admin/overview')) return body({ families: [], members: [] })
      if (url.includes('/admin/organisers')) return body(extra.organisers ?? [])
      if (url.includes('/admin/google-status')) {
        return body({
          checked_at: null,
          checked_by: null,
          browser_key_configured: false,
          server_key_configured: false,
          apis: [],
        })
      }
      if (url.includes('/admin/settings')) {
        return body({ instance_name: 'Kindred', registration_open: false, invite_only: true })
      }
      if (url.includes('/admin/stats')) {
        return body({
          families: 0,
          members: 0,
          invites_open: 0,
          polls_open: 0,
          polls_closed: 0,
          suggestions_by_status: { proposed: 0, approved: 0, scheduled: 0, rejected: 0 },
          comments: 0,
          itinerary_items: 0,
          checkins: 0,
          notifications_unread: 0,
        })
      }
      return body({}, 404)
    }),
  )
  vi.stubGlobal(
    'WebSocket',
    class {
      static OPEN = 1
      readyState = 0
      close() {}
      send() {}
    },
  )
}

describe('who the console renders for', () => {
  it('refuses a plain member with an explanation rather than a blank page', async () => {
    stubApp(baseUser)
    render(<App />)

    expect(
      await screen.findByRole('heading', { name: /do not have access to the admin console/i }),
    ).toBeInTheDocument()
    // And the nav entry was never there to click.
    expect(screen.queryByRole('button', { name: 'Admin console' })).not.toBeInTheDocument()
  })

  it('renders every section except Organisers for an organiser', async () => {
    stubApp({ ...baseUser, is_organiser: true })
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Admin console' })).toBeInTheDocument()
    for (const section of ['Trip', 'Stage', 'Voting modes', 'Google APIs', 'Stats']) {
      expect(screen.getByRole('heading', { name: section })).toBeInTheDocument()
    }
    // AC-13: the section is absent, not disabled — there is nothing here for them to see.
    expect(screen.queryByRole('heading', { name: 'Organisers' })).not.toBeInTheDocument()
  })

  it('renders the Organisers section for the owner', async () => {
    const organisers: Organiser[] = []
    stubApp({ ...baseUser, is_owner: true, is_organiser: true }, { organisers })
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Organisers' })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText(/No organisers yet/)).toBeInTheDocument(),
    )
  })

  it('shows the Admin nav entry to an organiser', async () => {
    stubApp({ ...baseUser, is_organiser: true })
    render(<App />)

    await screen.findByRole('heading', { name: 'Admin console' })
    expect(screen.getAllByRole('button', { name: 'Admin console' }).length).toBeGreaterThan(0)
  })
})

// --- role labels ------------------------------------------------------------------------------

describe('the member table role column', () => {
  it('shows every label that applies, because the two kinds of role are independent', async () => {
    const members: AdminMember[] = [
      {
        user_id: 'u2',
        username: 'stu',
        first_name: 'Stu',
        last_name: 'Rivera',
        display_name: 'Stu Rivera',
        initials: 'SR',
        avatar_thumb_url: null,
        family: {
          id: 'f2',
          name: 'The Riveras',
          color: 6,
          member_count: 3,
          home_locality: 'Newcastle',
          home_placed: true,
          geocode_status: 'ok',
          location_sharing_allowed: true,
        },
        family_role: 'head',
        is_owner: false,
        is_organiser: true,
        must_change_password: false,
        last_login_at: null,
        created_at: '2027-01-01T00:00:00Z',
      },
    ]
    stubApp({ ...baseUser, is_owner: true, is_organiser: true })
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input)
      const body = (payload: unknown) =>
        Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }))
      if (url.endsWith('/auth/me')) return body({ ...baseUser, is_owner: true, is_organiser: true })
      if (url.includes('/admin/overview')) return body({ families: [], members })
      if (url.includes('/admin/trip/stage-history')) return body([])
      if (url.includes('/admin/trip')) return body(trip())
      if (url.includes('/admin/organisers')) return body([])
      if (url.includes('/admin/category-settings')) return body([])
      if (url.includes('/admin/settings')) {
        return body({ instance_name: 'Kindred', registration_open: false, invite_only: true })
      }
      if (url.includes('/admin/google-status')) {
        return body({
          checked_at: null,
          checked_by: null,
          browser_key_configured: false,
          server_key_configured: false,
          apis: [],
        })
      }
      if (url.includes('/admin/stats')) {
        return body({
          families: 0,
          members: 0,
          invites_open: 0,
          polls_open: 0,
          polls_closed: 0,
          suggestions_by_status: { proposed: 0, approved: 0, scheduled: 0, rejected: 0 },
          comments: 0,
          itinerary_items: 0,
          checkins: 0,
          notifications_unread: 0,
        })
      }
      return body({})
    })
    render(<App />)

    // "Organiser · Head": one person, two independent roles, both shown.
    expect(await screen.findByText('Organiser · Head')).toBeInTheDocument()
    expect(screen.getByText('◌ Never logged in')).toBeInTheDocument()
  })
})
