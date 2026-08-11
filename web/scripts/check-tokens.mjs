/**
 * The token-only check (CI).
 *
 * Fails the build when application code contains a raw colour or an off-scale length.
 * The legacy app hardcoded one blue in 237 places and made restyling impossible; this is
 * the mechanical guard that stops Kindred repeating it, and it runs in CI rather than
 * relying on review to notice.
 *
 * Scope: `src/app/**`, `src/features/**` and `src/charts/**` — the places components live. `src/design/**`
 * is deliberately exempt: it is where literal values are *supposed* to be declared, and
 * `scripts/` is the generated-asset path documented in the PWA design.
 *
 * Run: `npm run check:tokens`
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, extname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const WEB_DIR = resolve(here, '..')
const SCANNED = ['src/app', 'src/features', 'src/charts']
const EXTENSIONS = new Set(['.css', '.ts', '.tsx'])

/**
 * Lengths a component may write directly.
 *  - the spacing scale 5 8 13 21 34 55, the type scale 13 16 20 26 42 68,
 *    the radii 6 10 16 999 and the 44px hit target — all of which have tokens, but a
 *    literal that lands on the scale is a style nit, not a drift risk;
 *  - 0 1 2 3 4: hairlines. A border is not a spacing decision and there is no
 *    "1px" token; forcing one would be ceremony.
 * Anything else is a number somebody made up, which is exactly what this catches.
 */
const ALLOWED_PX = new Set([0, 1, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 21, 26, 34, 42, 44, 55, 68, 999])

const HEX_COLOUR = /#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3}(?:[0-9a-fA-F]{2})?)?\b/g
const FUNCTIONAL_COLOUR = /\b(?:rgba?|hsla?|oklch|lab)\s*\(/g
const PX_VALUE = /(-?\d+(?:\.\d+)?)px/g

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    const full = resolve(dir, entry)
    if (statSync(full).isDirectory()) walk(full, files)
    else if (EXTENSIONS.has(extname(entry))) files.push(full)
  }
  return files
}

const violations = []

for (const scope of SCANNED) {
  const root = resolve(WEB_DIR, scope)
  for (const file of walk(root)) {
    const source = readFileSync(file, 'utf8')
    const lines = source.split(/\r?\n/)

    lines.forEach((line, index) => {
      const where = `${relative(WEB_DIR, file).replaceAll('\\', '/')}:${index + 1}`
      // A line may opt out with a reason. Used for nothing today; present so a genuine
      // exception is a visible, reviewable annotation rather than a disabled check.
      if (line.includes('token-check-ignore')) return

      for (const match of line.matchAll(HEX_COLOUR)) {
        violations.push(`${where}  raw colour ${match[0]} — use a semantic token`)
      }
      for (const match of line.matchAll(FUNCTIONAL_COLOUR)) {
        violations.push(
          `${where}  literal ${match[0]}) colour — use a token, or color-mix() with one`,
        )
      }
      for (const match of line.matchAll(PX_VALUE)) {
        const value = Math.abs(Number(match[1]))
        if (!ALLOWED_PX.has(value)) {
          violations.push(
            `${where}  off-scale length ${match[0]} — use a spacing/size token or add one`,
          )
        }
      }
    })
  }
}

if (violations.length > 0) {
  console.error(`Token check failed — ${violations.length} violation(s):\n`)
  for (const violation of violations) console.error(`  ${violation}`)
  console.error(
    '\nColours come from tokens.semantic.css; lengths from the 5/8/13/21/34/55 scale.',
  )
  process.exit(1)
}

console.log(`Token check passed — ${SCANNED.join(', ')} are token-only.`)
