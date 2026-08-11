import { describe, expect, it } from 'vitest'
import { routeFor } from './session'
import type { User } from './types'

const user = (overrides: Partial<User> = {}): User => ({
  id: 'u1',
  username: 'admin',
  display_name: 'Admin',
  is_platform_admin: true,
  must_change_password: false,
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
    expect(routeFor('authenticated', user({ must_change_password: true }))).toBe(
      'password-change',
    )
  })

  it('treats a missing user as anonymous even if the status disagrees', () => {
    // Defence in depth: the two pieces of state cannot contradict each other into
    // rendering the app to nobody.
    expect(routeFor('authenticated', null)).toBe('login')
  })
})
