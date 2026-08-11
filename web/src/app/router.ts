/**
 * A minimal, honest router.
 *
 * M0 had none: there was one destination, so `routes.tsx` rendered whichever of three
 * screens the session allowed and called it routing. `families` is the first feature with
 * more than one screen — and two of them, `/join/<token>` and `/setup/family`, are reached
 * by URL rather than by clicking — so a real one arrives here, as the M0 hand-off said it
 * would.
 *
 * Deliberately small: `history.pushState` plus a subscription. No dependency, no route
 * table, no nested layouts, because the app has five destinations and a library would be
 * more machinery than the problem has.
 *
 * **The router does not decide what a session may see.** That is the server's `next_step`
 * gate (`session.ts`), and the two are kept apart on purpose: a router that could also
 * grant access is a router someone will eventually route around.
 */

import { useCallback, useEffect, useState } from 'react'

/** In-app destinations. The two setup screens are not here — they are gates, not places. */
export type AppRoute =
  | { name: 'home' }
  | { name: 'families'; familyId?: string }
  | { name: 'profile' }
  | { name: 'join'; token: string }
  | { name: 'setup-family' }
  | { name: 'not-found'; path: string }

export function parsePath(path: string): AppRoute {
  const parts = path.replace(/\/+$/, '').split('/').filter(Boolean)
  if (parts.length === 0) return { name: 'home' }
  if (parts[0] === 'join' && parts[1]) return { name: 'join', token: parts.slice(1).join('/') }
  if (parts[0] === 'setup' && parts[1] === 'family') return { name: 'setup-family' }
  if (parts[0] === 'families') return { name: 'families', familyId: parts[1] }
  if (parts[0] === 'profile') return { name: 'profile' }
  return { name: 'not-found', path }
}

export function pathFor(route: AppRoute): string {
  switch (route.name) {
    case 'home':
      return '/'
    case 'families':
      return route.familyId ? `/families/${route.familyId}` : '/families'
    case 'profile':
      return '/profile'
    case 'join':
      return `/join/${route.token}`
    case 'setup-family':
      return '/setup/family'
    case 'not-found':
      return route.path
  }
}

type Listener = () => void
const listeners = new Set<Listener>()

function notify() {
  for (const listener of listeners) listener()
}

/** Change the URL without a reload. `replace` for redirects, so Back still works. */
export function navigate(to: AppRoute | string, options: { replace?: boolean } = {}): void {
  const path = typeof to === 'string' ? to : pathFor(to)
  if (path === window.location.pathname) return
  if (options.replace) window.history.replaceState(null, '', path)
  else window.history.pushState(null, '', path)
  notify()
}

/** The current route, re-rendered on `popstate` and on our own `navigate` calls. */
export function useRoute(): AppRoute {
  const [path, setPath] = useState(() => window.location.pathname)

  useEffect(() => {
    const update = () => setPath(window.location.pathname)
    // Both, because `pushState` fires no event of its own: `popstate` covers the back
    // button, and the listener set covers our own navigations.
    listeners.add(update)
    window.addEventListener('popstate', update)
    return () => {
      listeners.delete(update)
      window.removeEventListener('popstate', update)
    }
  }, [])

  return parsePath(path)
}

/** `navigate`, stable across renders, for handlers. */
export function useNavigate() {
  return useCallback((to: AppRoute | string, options?: { replace?: boolean }) => {
    navigate(to, options)
  }, [])
}
