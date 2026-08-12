/**
 * ScoreVoteControl — the 0–10 score-mode vote input (`design.md` > "Vote controls").
 *
 * Each step is tinted with the shared `--scale-pref-0…10` ramp (colourblind-safe,
 * `plan/design-system.md`) and always carries its digit as text — colour is never the sole
 * carrier of the value, on the button itself or in the summary beside it. Full keyboard
 * operation: arrow keys move a roving `tabIndex` along the scale, Enter/Space commits the
 * focused step (native button behaviour — nothing extra to wire for that half). Touch
 * targets are ≥44px via `--hit-target`.
 */

import { useRef } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import './voting.css'

const STEPS = Array.from({ length: 11 }, (_, i) => i)

export type ScoreVoteControlProps = {
  /** The caller's current vote, or `null` when they have not voted. */
  value: number | null
  onChange: (value: number) => void
  disabled?: boolean
  /** Compact renders a smaller strip (popover card); full is the side-panel size. */
  size?: 'compact' | 'full'
  label?: string
}

export function ScoreVoteControl({
  value,
  onChange,
  disabled = false,
  size = 'full',
  label = 'Your score',
}: ScoreVoteControlProps) {
  const groupRef = useRef<HTMLDivElement>(null)
  // Roving tabIndex starts at the current value, or the middle of the scale when unvoted.
  const focusable = value ?? 5

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const current = document.activeElement as HTMLElement | null
    const currentIndex = current ? Number(current.dataset.step) : focusable
    const nextIndex = Math.min(10, Math.max(0, currentIndex + (event.key === 'ArrowRight' ? 1 : -1)))
    const nextEl = groupRef.current?.querySelector<HTMLElement>(`[data-step="${nextIndex}"]`)
    nextEl?.focus()
  }

  return (
    <div className={`vc-score vc-score--${size}`}>
      <div
        ref={groupRef}
        className="vc-score__steps"
        role="radiogroup"
        aria-label={label}
        onKeyDown={onKeyDown}
      >
        {STEPS.map((step) => (
          <button
            key={step}
            type="button"
            role="radio"
            data-step={step}
            aria-checked={value === step}
            tabIndex={step === focusable ? 0 : -1}
            className={`vc-score__step${value === step ? ' is-on' : ''}`}
            style={{ '--step-color': `var(--scale-pref-${step})` } as CSSProperties}
            disabled={disabled}
            onClick={() => onChange(step)}
          >
            {step}
          </button>
        ))}
      </div>
      {/* The chosen number, as text, beside the control — never colour/position alone. */}
      <span className="vc-score__value tabular">{value ?? '—'}</span>
    </div>
  )
}
