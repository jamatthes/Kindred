import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from '../App'
import type { User } from './types'

const admin: User = {
  id: 'u1',
  username: 'admin',
  display_name: 'Admin',
  is_platform_admin: true,
  must_change_password: false,
  theme_pref: 'light',
  locale: 'en-GB',
  family: null,
  trip: {
    id: 't1',
    name: 'Cornwall · July 2027',
    stage: 'planning',
    start_date: '2027-07-17',
    end_date: '2027-07-24',
    timezone: 'Europe/London',
  },
}

/** Answers the calls the shell makes on load; anything else is a 404 we want to notice. */
function stubApi(me: User | null) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string) => {
      const url = String(input)
      if (url.endsWith('/auth/me')) {
        return Promise.resolve(
          me
            ? new Response(JSON.stringify(me), { status: 200 })
            : new Response(
                JSON.stringify({ detail: { code: 'not_authenticated', message: 'Log in.' } }),
                { status: 401 },
              ),
        )
      }
      if (url.endsWith('/settings')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              instance_name: 'The Cornwall Crew',
              registration_open: false,
              invite_only: true,
            }),
            { status: 200 },
          ),
        )
      }
      if (url.endsWith('/presence')) {
        return Promise.resolve(new Response(JSON.stringify({ online_user_ids: [] }), { status: 200 }))
      }
      return Promise.resolve(new Response('{}', { status: 404 }))
    }),
  )
  // jsdom has no WebSocket implementation worth exercising here; the shell only needs it
  // not to throw.
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

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the shell gate', () => {
  it('shows the login screen, headed by the instance name, when nobody is signed in', async () => {
    stubApi(null)
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'The Cornwall Crew' })).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })

  it('renders the shell and the trip for a signed-in user', async () => {
    stubApi(admin)
    render(<App />)

    // Once in the top bar, once as the page heading.
    expect(await screen.findAllByText('Cornwall · July 2027')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: 'Cornwall · July 2027' })).toBeInTheDocument()
    expect(screen.getAllByRole('navigation', { name: 'Main' }).length).toBeGreaterThan(0)
    // The theme control is part of the shell, not a feature.
    expect(screen.getByRole('group', { name: 'Theme' })).toBeInTheDocument()
  })

  it('pins a must-change-password user to the change screen with no way out', async () => {
    stubApi({ ...admin, must_change_password: true })
    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Choose a new password' }),
    ).toBeInTheDocument()
    // No nav rail, no tab bar, no shell chrome — only the form and a way to log out.
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    expect(screen.queryByText('Cornwall · July 2027')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
  })

  it('applies the theme the server records for the user', async () => {
    stubApi({ ...admin, theme_pref: 'dark' })
    render(<App />)

    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe('dark'),
    )
  })
})

describe('the theme control', () => {
  it('rolls back and explains itself when the server refuses the change', async () => {
    stubApi(admin) // recorded preference: light
    render(<App />)
    await screen.findByRole('group', { name: 'Theme' })
    expect(document.documentElement.dataset.theme).toBe('light')

    // The PATCH fails — the optimistic switch must not survive it.
    vi.mocked(fetch).mockImplementation((input: string | URL | Request) => {
      if (String(input).endsWith('/me/preferences')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ detail: { code: 'forbidden', message: 'Not allowed.' } }),
            { status: 403 },
          ),
        )
      }
      return Promise.resolve(new Response('{}', { status: 404 }))
    })

    fireEvent.click(screen.getByRole('button', { name: 'Dark theme' }))

    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'))
    expect(screen.getByRole('group', { name: 'Theme' })).toHaveAttribute('title', 'Not allowed.')
    expect(screen.getByRole('button', { name: 'Light theme' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})
