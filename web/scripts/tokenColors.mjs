/**
 * Reads colour values out of the token CSS at build time.
 *
 * A manifest is static JSON and an icon is a raster: neither can reference a CSS custom
 * property, so the two or three literal colours they need are *generated* from the token
 * source rather than authored. That is the one sanctioned exception to the token-only rule
 * (`plan/features/pwa-push/design.md`), and it only holds while the value is derived here
 * instead of being typed by hand.
 *
 * The resolver follows one level of `var()` indirection, which is all the semantic layer
 * uses: `--color-accent: var(--coral-500)` → `--coral-500: #D95940`.
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const DESIGN_DIR = resolve(here, '..', 'src', 'design')

function declarations(file) {
  const css = readFileSync(resolve(DESIGN_DIR, file), 'utf8')
  const found = new Map()
  // Light theme only: a manifest has one theme colour, and the install/splash surface is
  // the light one. Stop at the dark block so its values cannot win.
  const lightOnly = css.split('[data-theme="dark"]')[0]
  for (const [, name, value] of lightOnly.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    if (!found.has(name)) found.set(name, value.trim())
  }
  return found
}

const primitives = declarations('tokens.primitives.css')
const semantic = declarations('tokens.semantic.css')

/** Resolve a token name to a literal colour, following `var()` once. */
export function tokenColor(name) {
  const raw = semantic.get(name) ?? primitives.get(name)
  if (raw === undefined) throw new Error(`Unknown design token: ${name}`)
  const indirect = raw.match(/^var\((--[\w-]+)\)$/)
  const value = indirect ? (primitives.get(indirect[1]) ?? semantic.get(indirect[1])) : raw
  if (value === undefined || !value.startsWith('#')) {
    throw new Error(`Token ${name} does not resolve to a literal colour (got ${raw})`)
  }
  return value
}

export const brandColors = () => ({
  accent: tokenColor('--color-accent'),
  onAccent: tokenColor('--color-text-on-accent'),
  background: tokenColor('--color-bg'),
})
