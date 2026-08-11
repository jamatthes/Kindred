/**
 * Theme controller: Light / Dark / System.
 *
 * The server record on `users.theme_pref` is the source of truth — the choice follows the
 * user to any device. localStorage holds a *cache* of it, read by the blocking inline
 * script in `index.html` before first paint so a dark-theme user never sees a white flash.
 * The two reconcile when `auth/me` resolves.
 *
 * "System" is not a third palette: it resolves to light or dark and re-resolves live when
 * the OS setting changes, per the edge-case table in the foundation design.
 */

import type { ThemePref } from '../app/types'

/** Shared with the inline script in `index.html`. Changing it invalidates every cache. */
export const THEME_STORAGE_KEY = 'kindred.theme'

export type ResolvedTheme = 'light' | 'dark'

const MEDIA_QUERY = '(prefers-color-scheme: dark)'

export function isThemePref(value: unknown): value is ThemePref {
  return value === 'light' || value === 'dark' || value === 'system'
}

export function systemTheme(): ResolvedTheme {
  return window.matchMedia?.(MEDIA_QUERY).matches ? 'dark' : 'light'
}

export function resolveTheme(pref: ThemePref): ResolvedTheme {
  return pref === 'system' ? systemTheme() : pref
}

/** Read the cached preference. Returns `system` when nothing is cached or it is corrupt. */
export function readCachedTheme(): ThemePref {
  try {
    const cached = localStorage.getItem(THEME_STORAGE_KEY)
    return isThemePref(cached) ? cached : 'system'
  } catch {
    // Private browsing modes throw on storage access. A missing cache costs a possible
    // flash, never a crash.
    return 'system'
  }
}

export function cacheTheme(pref: ThemePref): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, pref)
  } catch {
    /* see readCachedTheme */
  }
}

/**
 * Put the resolved theme on <html>. This is the only place `data-theme` is written, so the
 * attribute can never disagree with the token layer's expectations.
 */
export function applyTheme(pref: ThemePref): ResolvedTheme {
  const resolved = resolveTheme(pref)
  document.documentElement.dataset.theme = resolved
  return resolved
}

/**
 * Watch the OS setting. The callback fires only while the preference is `system`; the
 * caller re-subscribes when the preference changes.
 */
export function watchSystemTheme(onChange: (resolved: ResolvedTheme) => void): () => void {
  const media = window.matchMedia?.(MEDIA_QUERY)
  if (!media) return () => {}
  const handler = (event: MediaQueryListEvent) => onChange(event.matches ? 'dark' : 'light')
  media.addEventListener('change', handler)
  return () => media.removeEventListener('change', handler)
}
