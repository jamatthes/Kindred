/** Vitest setup: DOM matchers, and a jsdom that admits what it cannot do. */
import '@testing-library/jest-dom/vitest'

// This jsdom build exposes no Storage (Node's own experimental `localStorage` shadows it
// and is disabled without --localstorage-file), so tests get a minimal in-memory one. The
// theme controller already survives its absence — every access is wrapped — but a test
// that cannot store anything cannot prove the cache round-trips.
if (typeof window !== 'undefined' && window.localStorage === undefined) {
  const store = new Map<string, string>()
  const memoryStorage: Storage = {
    get length() {
      return store.size
    },
    key: (index) => [...store.keys()][index] ?? null,
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => void store.set(key, String(value)),
    removeItem: (key) => void store.delete(key),
    clear: () => store.clear(),
  }
  Object.defineProperty(window, 'localStorage', { value: memoryStorage, configurable: true })
  Object.defineProperty(globalThis, 'localStorage', {
    value: memoryStorage,
    configurable: true,
  })
}

// jsdom has no matchMedia, and the theme controller asks for it on every resolve.
if (typeof window !== 'undefined' && window.matchMedia === undefined) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}
