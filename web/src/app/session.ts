/**
 * Session bootstrap, the in-memory user context, and the routing rules that depend on it.
 *
 * One `auth/me` on load decides everything: no user → login; `must_change_password` → the
 * change screen, from any route, with no way past it; otherwise the app. The rule lives
 * here rather than in each screen so there is exactly one place that can be wrong.
 *
 * The theme lives here too, because it is part of the user record: the control is
 * optimistic and rolls back on failure, and the localStorage cache that prevents a
 * first-paint flash is kept in step with the server value.
 *
 * No JSX in this file — it is `.ts` per the foundation file tree, so the provider is built
 * with `createElement`.
 */

import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, api, onUnauthorized } from './apiClient'
import type { LoginResponse, NextStep, Preferences, ThemePref, User } from './types'
import {
  applyTheme,
  cacheTheme,
  readCachedTheme,
  resolveTheme,
  watchSystemTheme,
} from '../design/theme'
import type { ResolvedTheme } from '../design/theme'

export type SessionStatus = 'loading' | 'anonymous' | 'authenticated'

/** Which top-level screen the app is allowed to show. */
export type Route =
  | 'loading'
  | 'login'
  | 'password-change'
  | 'setup-trip'
  | 'setup-family'
  | 'app'

/**
 * The gate, and the whole of it.
 *
 * Everything past "is there a session at all" comes from the server's `next_step`
 * (`plan/architecture.md`, foundation F-13). The client is told the *answer*, never the
 * precedence — so there is no order here to get wrong, and no combination of flags a user
 * could arrange to slip past a screen. `plan/features/families/tasks.md` Phase 10 says it
 * outright: "Routing reads `next_step` from `auth/me` and nothing else. Do not reimplement
 * the precedence in the client."
 *
 * The mapping below is a rename, not a decision: each `next_step` value names one screen.
 */
const SCREEN_FOR_NEXT_STEP: Record<NextStep, Route> = {
  change_password: 'password-change',
  setup_trip: 'setup-trip',
  setup_family: 'setup-family',
  app: 'app',
}

export function routeFor(status: SessionStatus, user: User | null): Route {
  if (status === 'loading') return 'loading'
  if (status === 'anonymous' || user === null) return 'login'
  return SCREEN_FOR_NEXT_STEP[user.next_step] ?? 'app'
}

export type SessionValue = {
  status: SessionStatus
  user: User | null
  /**
   * Adopt a user the caller already has. The join screen registers and is handed the new
   * user in the same response, so re-fetching `auth/me` to learn what it was just told
   * would be a round trip spent confirming something already known.
   */
  adoptUser: (user: User) => void
  route: Route
  themePref: ThemePref
  resolvedTheme: ResolvedTheme
  /** Set when the last theme change failed and was rolled back. */
  themeError: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  setThemePref: (pref: ThemePref) => Promise<void>
  refresh: () => Promise<void>
}

const SessionContext = createContext<SessionValue | null>(null)

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (value === null) throw new Error('useSession must be used inside <SessionProvider>')
  return value
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [user, setUser] = useState<User | null>(null)
  const [themePref, setTheme] = useState<ThemePref>(() => readCachedTheme())
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() =>
    resolveTheme(readCachedTheme()),
  )
  const [themeError, setThemeError] = useState<string | null>(null)
  // Guards the reconcile-on-load below from fighting a change the user just made.
  const themeTouched = useRef(false)

  const applyPref = useCallback((pref: ThemePref) => {
    setTheme(pref)
    setResolvedTheme(applyTheme(pref))
    cacheTheme(pref)
  }, [])

  const adoptUser = useCallback(
    (next: User) => {
      setUser(next)
      setStatus('authenticated')
      // The server record wins over the local cache — that is what makes the preference
      // follow you to a new device — unless the user has already changed it this session.
      if (!themeTouched.current) applyPref(next.theme_pref)
    },
    [applyPref],
  )

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<User>('/auth/me', { signalUnauthorized: false })
      adoptUser(me)
    } catch {
      // 401 is the normal "not logged in yet" answer on a cold load, not an error worth
      // showing. Anything else (server down) also lands on login, which offers a retry.
      setUser(null)
      setStatus('anonymous')
    }
  }, [adoptUser])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Any 401 anywhere in the app drops us to login — including the second tab after the
  // first one logs out.
  useEffect(
    () =>
      onUnauthorized(() => {
        setUser(null)
        setStatus('anonymous')
      }),
    [],
  )

  // The inline script in index.html has already painted with the cached preference; this
  // makes React's idea of the theme agree with the DOM's on mount.
  useEffect(() => {
    setResolvedTheme(applyTheme(readCachedTheme()))
  }, [])

  // `system` is live: when the OS flips, so do we.
  useEffect(() => {
    if (themePref !== 'system') return
    return watchSystemTheme((next) => {
      document.documentElement.dataset.theme = next
      setResolvedTheme(next)
    })
  }, [themePref])

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await api.post<LoginResponse>('/auth/login', { username, password })
      themeTouched.current = false
      adoptUser(result.user)
    },
    [adoptUser],
  )

  const logout = useCallback(async () => {
    try {
      await api.post<void>('/auth/logout')
    } finally {
      // Whatever the server said, this browser is done: a failed logout must not strand
      // the user in a session they asked to leave.
      setUser(null)
      setStatus('anonymous')
    }
  }, [])

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      await api.post<void>('/auth/password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      await refresh()
    },
    [refresh],
  )

  const setThemePref = useCallback(
    async (pref: ThemePref) => {
      const previous = themePref
      themeTouched.current = true
      setThemeError(null)
      applyPref(pref) // optimistic: the switch is instant, the request catches up
      try {
        const saved = await api.patch<Preferences>('/me/preferences', { theme_pref: pref })
        applyPref(saved.theme_pref)
        setUser((current) => (current ? { ...current, theme_pref: saved.theme_pref } : current))
      } catch (error) {
        applyPref(previous)
        setThemeError(
          error instanceof ApiError ? error.message : 'Your theme could not be saved.',
        )
      }
    },
    [applyPref, themePref],
  )

  const value = useMemo<SessionValue>(
    () => ({
      status,
      user,
      adoptUser,
      route: routeFor(status, user),
      themePref,
      resolvedTheme,
      themeError,
      login,
      logout,
      changePassword,
      setThemePref,
      refresh,
    }),
    [status, user, adoptUser, themePref, resolvedTheme, themeError, login, logout, changePassword, setThemePref, refresh],
  )

  return createElement(SessionContext.Provider, { value }, children)
}
