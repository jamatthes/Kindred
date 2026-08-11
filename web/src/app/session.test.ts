import { describe, expect, it } from 'vitest'
import { routeFor } from './session'
import type { User } from './types'

const user = (overrides: Partial<User> = {}): User => ({
  id: 'u1',
  username: 'admin',
  first_name: 'Admin',
  last_name: '',
  avatar_url: null,
  avatar_thumb_url: null,
  initials: 'A',
  display_name: 'Admin',
  is_platform_admin: true,
  is_owner: true,
  is_organiser: true,
  must_change_password: false,
  next_step: 'app',
  theme_pref: 'system',
  locale: 'en-GB',
  family: null,
  trip: null,
  ...overrides,
})

describe('routeFor — the gate the whole shell hangs on', () => {
  it('shows nothing until auth/me has answered', () => {
    expect(routeFor('loading', null)).toBe('loading')
    // Even with a user object in hand, `loading` wins: rendering the app and then
    // yanking it away is worse than a skeleton.
    expect(routeFor('loading', user())).toBe('loading')
  })

  it('sends an anonymous visitor to login', () => {
    expect(routeFor('anonymous', null)).toBe('login')
  })

  it('sends an authenticated user to the app', () => {
    expect(routeFor('authenticated', user())).toBe('app')
  })

  it('pins a must-change-password user to the change screen', () => {
    // The *server* decides this, and says so in `next_step`. The client used to derive it
    // from `must_change_password`; it no longer does, because there are four gates now and a
    // client-side precedence is a second place for the order to be wrong. `families` moved
    // it (foundation F-13, `app/core/onboarding.py`).
    expect(
      routeFor('authenticated', user({ must_change_password: true, next_step: 'change_password' })),
    ).toBe('password-change')
  })

  it('routes on next_step alone, not on the flags behind it', () => {
    // The proof that the precedence really did move: a user whose flag says one thing and
    // whose `next_step` says another follows `next_step`. Only the server can be right here,
    // because only the server can see all four conditions.
    expect(routeFor('authenticated', user({ must_change_password: true, next_step: 'app' }))).toBe(
      'app',
    )
  })

  it('knows the two first-login setup screens', () => {
    expect(routeFor('authenticated', user({ next_step: 'setup_family' }))).toBe('setup-family')
    expect(routeFor('authenticated', user({ next_step: 'setup_trip' }))).toBe('setup-trip')
  })

  it('treats a missing user as anonymous even if the status disagrees', () => {
    // Defence in depth: the two pieces of state cannot contradict each other into
    // rendering the app to nobody.
    expect(routeFor('authenticated', null)).toBe('login')
  })
})
