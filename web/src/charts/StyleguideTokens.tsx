/**
 * `/styleguide` — token gallery section.
 *
 * Renders the token scales side by side in both themes at once (each panel carries its
 * own `data-theme`, independent of the page-level toggle in `Styleguide.tsx`), with a
 * live contrast readout computed from the browser's actual resolved custom-property
 * values via `getComputedStyle` — not hand-copied numbers that go stale the next time
 * the DesignSync pass changes a value.
 *
 * `plan/features/design-system/tasks.md` Phase 8: "colour swatches with names and
 * computed values… a contrast readout beside each colour pairing… the preference ramp
 * shown three ways side by side… spacing, type ramp, radii, shadows."
 */

import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { aaLevel, contrastRatio } from './contrast'
import './StyleguideTokens.css'

function useResolvedVar(scopeRef: RefObject<HTMLElement | null>, name: string): string {
  const [value, setValue] = useState('')
  useEffect(() => {
    const el = scopeRef.current
    if (!el) return
    // Tokens are static for the lifetime of a mounted panel — there is no live token
    // editor — so reading once after mount (rather than every render) is correct, not
    // just cheaper.
    setValue(getComputedStyle(el).getPropertyValue(name).trim())
  }, [scopeRef, name])
  return value
}

function ColorSwatch({
  scopeRef,
  name,
  label,
}: {
  scopeRef: RefObject<HTMLElement | null>
  name: string
  label: string
}) {
  const value = useResolvedVar(scopeRef, name)
  return (
    <div className="k-sg-swatch">
      <span className="k-sg-swatch__chip" style={{ background: `var(${name})` }} aria-hidden="true" />
      <span className="k-sg-swatch__name">{label}</span>
      <span className="k-sg-swatch__value">{value || '—'}</span>
    </div>
  )
}

function ContrastRow({
  scopeRef,
  fg,
  bg,
  label,
  large = false,
}: {
  scopeRef: RefObject<HTMLElement | null>
  fg: string
  bg: string
  label: string
  large?: boolean
}) {
  const fgValue = useResolvedVar(scopeRef, fg)
  const bgValue = useResolvedVar(scopeRef, bg)
  const ratio = contrastRatio(fgValue, bgValue)
  const level = aaLevel(ratio, large)
  const pass = level !== 'fail'
  return (
    <div className="k-sg-contrast-row" style={{ background: `var(${bg})`, color: `var(${fg})` }}>
      <span className="k-sg-contrast-row__label">{label}</span>
      <span className="k-sg-contrast-row__ratio">{ratio ? `${ratio.toFixed(2)}:1` : '—'}</span>
      <span
        className={`k-sg-badge ${pass ? 'k-sg-badge--pass' : 'k-sg-badge--fail'}`}
        data-testid="aa-badge"
      >
        {pass ? `Pass (${level})` : 'Fail'}
      </span>
    </div>
  )
}

const STATUS_PAIRS: { label: string; fg: string; bg: string }[] = [
  { label: 'Text on background', fg: '--color-text', bg: '--color-bg' },
  { label: 'Muted text on surface', fg: '--color-text-muted', bg: '--color-surface' },
  { label: 'Text on accent', fg: '--color-text-on-accent', bg: '--color-accent' },
  { label: 'Success on success-soft', fg: '--color-success', bg: '--color-success-soft' },
  { label: 'Warning on warning-soft', fg: '--color-warning', bg: '--color-warning-soft' },
  { label: 'Danger on danger-soft', fg: '--color-danger', bg: '--color-danger-soft' },
  { label: 'Info on info-soft', fg: '--color-info', bg: '--color-info-soft' },
]

const SURFACE_SWATCHES = [
  '--color-bg',
  '--color-surface',
  '--color-surface-raised',
  '--color-surface-sunken',
  '--color-border',
  '--color-border-strong',
]

const TEXT_SWATCHES = ['--color-text', '--color-text-muted', '--color-text-faint']

const STATUS_SWATCHES = ['--color-accent', '--color-success', '--color-warning', '--color-danger', '--color-info']

const FAMILY_SWATCHES = Array.from({ length: 8 }, (_, i) => `--family-${i + 1}`)

const PREF_STEPS = Array.from({ length: 11 }, (_, i) => i)

const TYPE_SCALE = [
  { name: '--text-sm', label: 'sm (13)' },
  { name: '--text-body', label: 'body (16)' },
  { name: '--text-lg', label: 'lg (20)' },
  { name: '--text-sub', label: 'sub (26)' },
  { name: '--text-heading', label: 'heading (42)' },
  { name: '--text-display', label: 'display (68)' },
]

const SPACE_SCALE = [
  { name: '--space-1', label: '1 (5)' },
  { name: '--space-2', label: '2 (8)' },
  { name: '--space-3', label: '3 (13)' },
  { name: '--space-4', label: '4 (21)' },
  { name: '--space-5', label: '5 (34)' },
  { name: '--space-6', label: '6 (55)' },
]

const RADII = ['--radius-1', '--radius-2', '--radius-3', '--radius-full']
const SHADOWS = ['--shadow-1', '--shadow-2', '--shadow-3']

/** One theme's full token panel: surfaces, text, status, families, ramp, contrast. */
function ThemePanel({ theme }: { theme: 'light' | 'dark' }) {
  const ref = useRef<HTMLDivElement>(null)

  return (
    <div className="k-sg-panel" data-theme={theme} ref={ref}>
      <p className="k-sg-panel__label">{theme === 'light' ? 'Light' : 'Dark'}</p>

      <p className="k-sg-subhead">Surfaces &amp; borders</p>
      <div className="k-sg-swatch-grid">
        {SURFACE_SWATCHES.map((name) => (
          <ColorSwatch key={name} scopeRef={ref} name={name} label={name} />
        ))}
      </div>

      <p className="k-sg-subhead">Text</p>
      <div className="k-sg-swatch-grid">
        {TEXT_SWATCHES.map((name) => (
          <ColorSwatch key={name} scopeRef={ref} name={name} label={name} />
        ))}
      </div>

      <p className="k-sg-subhead">Status</p>
      <div className="k-sg-swatch-grid">
        {STATUS_SWATCHES.map((name) => (
          <ColorSwatch key={name} scopeRef={ref} name={name} label={name} />
        ))}
      </div>

      <p className="k-sg-subhead">Family colours (8 slots)</p>
      <div className="k-sg-swatch-grid">
        {FAMILY_SWATCHES.map((name) => (
          <ColorSwatch key={name} scopeRef={ref} name={name} label={name} />
        ))}
      </div>

      <p className="k-sg-subhead">Preference ramp 0–10 — swatches</p>
      <div className="k-sg-ramp-row">
        {PREF_STEPS.map((step) => (
          <div key={step} className="k-sg-ramp-step">
            <span className="k-sg-ramp-step__chip" style={{ background: `var(--scale-pref-${step})` }} />
            <span className="k-sg-ramp-step__num">{step}</span>
          </div>
        ))}
      </div>

      <p className="k-sg-subhead">Preference ramp — map-style tints</p>
      <p className="k-sg-caption">
        The same tint recipe HeatMatrix cells use (`color-mix()` at `--mix-tint-strong` onto
        `--color-surface`) — a map region pin would tint the same way, from the same tokens.
      </p>
      <div className="k-sg-ramp-row">
        {PREF_STEPS.map((step) => (
          <div key={step} className="k-sg-ramp-step">
            <span
              className="k-sg-ramp-step__chip k-sg-ramp-step__chip--tint"
              style={{
                background: `color-mix(in srgb, var(--scale-pref-${step}) var(--mix-tint-strong), var(--color-surface))`,
              }}
            >
              {step}
            </span>
          </div>
        ))}
      </div>

      <p className="k-sg-subhead">Contrast readout</p>
      <div className="k-sg-contrast-list">
        {STATUS_PAIRS.map((pair) => (
          <ContrastRow key={pair.label} scopeRef={ref} {...pair} />
        ))}
      </div>
    </div>
  )
}

/** Theme-invariant scales — spacing and type sizes are fixed by design-system.md and
 *  don't need a light/dark comparison, so these render once, outside the panels. */
function InvariantScales() {
  return (
    <div className="k-sg-invariant">
      <p className="k-sg-subhead">Type scale</p>
      <div className="k-sg-type-scale">
        {TYPE_SCALE.map((step) => (
          <div key={step.name} className="k-sg-type-row">
            <span className="k-sg-type-row__label">{step.label}</span>
            <span className="k-sg-type-row__sample" style={{ fontSize: `var(${step.name})` }}>
              Aa
            </span>
          </div>
        ))}
      </div>

      <p className="k-sg-subhead">Spacing scale</p>
      <div className="k-sg-space-scale">
        {SPACE_SCALE.map((step) => (
          <div key={step.name} className="k-sg-space-row">
            <span className="k-sg-space-row__label">{step.label}</span>
            <span className="k-sg-space-row__bar" style={{ width: `var(${step.name})` }} />
          </div>
        ))}
      </div>

      <p className="k-sg-subhead">Radii &amp; shadows</p>
      <div className="k-sg-radii-row">
        {RADII.map((name) => (
          <span key={name} className="k-sg-radius-sample" style={{ borderRadius: `var(${name})` }}>
            {name}
          </span>
        ))}
      </div>
      <div className="k-sg-radii-row">
        {SHADOWS.map((name) => (
          <span key={name} className="k-sg-shadow-sample" style={{ boxShadow: `var(${name})` }}>
            {name}
          </span>
        ))}
      </div>
    </div>
  )
}

export function StyleguideTokens() {
  return (
    <div>
      <InvariantScales />
      <div className="k-sg-panels">
        <ThemePanel theme="light" />
        <ThemePanel theme="dark" />
      </div>
    </div>
  )
}
