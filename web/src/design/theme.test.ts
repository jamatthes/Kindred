import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  THEME_STORAGE_KEY,
  applyTheme,
  cacheTheme,
  isThemePref,
  readCachedTheme,
  resolveTheme,
} from './theme'

function stubSystemDark(dark: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: dark,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  delete document.documentElement.dataset.theme
})

describe('theme controller', () => {
  it('resolves system to the OS setting and everything else to itself', () => {
    stubSystemDark(true)
    expect(resolveTheme('system')).toBe('dark')
    expect(resolveTheme('light')).toBe('light')
    stubSystemDark(false)
    expect(resolveTheme('system')).toBe('light')
    // An explicit choice ignores the OS — that is the point of choosing.
    expect(resolveTheme('dark')).toBe('dark')
  })

  it('writes the resolved theme to <html>, never the preference name', () => {
    stubSystemDark(true)
    expect(applyTheme('system')).toBe('dark')
    // `system` must never reach the attribute: the token layer only knows light and dark.
    expect(document.documentElement.dataset.theme).toBe('dark')

    applyTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('round-trips the cache the inline no-flash script reads', () => {
    cacheTheme('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(readCachedTheme()).toBe('dark')
  })

  it('falls back to system when the cache is absent or corrupt', () => {
    expect(readCachedTheme()).toBe('system')
    localStorage.setItem(THEME_STORAGE_KEY, 'chartreuse')
    expect(readCachedTheme()).toBe('system')
  })

  it('validates preference values', () => {
    expect(isThemePref('light')).toBe(true)
    expect(isThemePref('system')).toBe(true)
    expect(isThemePref('sepia')).toBe(false)
    expect(isThemePref(null)).toBe(false)
  })
})
