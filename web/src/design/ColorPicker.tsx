/**
 * The family colour picker (2026-08-11 palette ruling).
 *
 * A 24-swatch grid, reused by both `FamilySetupScreen` (choosing at creation) and
 * `FamilyPanel` (changing later, gated to the family-manager permission there — this
 * component itself has no opinion on who may use it, only a `disabled` prop). Swatches
 * already claimed by another family are shown disabled with a "taken" treatment and an
 * accessible name ("Coral (taken)"); the grid is keyboard-navigable with arrow keys, one tab
 * stop (roving `tabIndex`), as a `radiogroup` of `radio`s.
 *
 * Once the server reports the palette exhausted (`GET /families/palette` → `exhausted:
 * true`), the grid is replaced entirely by a native `<input type="color">` colour wheel —
 * the overflow escape hatch for the 25th family and later. The two are mutually exclusive by
 * design: the wheel is not offered while a slot is still free, matching the server's
 * `422 custom_color_not_allowed`.
 */

import { useRef } from 'react'
import type { KeyboardEvent } from 'react'
import './ColorPicker.css'

export const PALETTE_SIZE = 24

//: Matches `--family-1…24` in `web/src/design/tokens.primitives.css`, in order. Used only for
//: the accessible name ("Coral (taken)") — the swatch itself is drawn from the CSS variable
//: so a design-system retune never has to touch this file.
export const PALETTE_NAMES = [
  'Rose',
  'Orange',
  'Gold',
  'Moss',
  'Teal',
  'Sky',
  'Indigo',
  'Plum',
  'Amber',
  'Olive',
  'Fern',
  'Grass',
  'Jade',
  'Emerald',
  'Aqua',
  'Azure',
  'Cornflower',
  'Violet',
  'Iris',
  'Orchid',
  'Magenta',
  'Berry',
  'Cherry',
  'Terracotta',
]

export type ColorPickerValue = { color: number | null; color_custom: string | null }

export type ColorPickerProps = {
  value: ColorPickerValue
  /** Every slot currently claimed on the trip (`GET /families/palette`'s `taken_colors`). The
   * caller's own currently-held slot, if any, should still be included here — this component
   * treats `value.color` as selectable regardless of whether it appears in this list. */
  takenColors: number[]
  /** `GET /families/palette`'s `exhausted` — true once all 24 slots are claimed. Switches the
   * whole control from the grid to the colour wheel. */
  exhausted: boolean
  onChange: (next: ColorPickerValue) => void
  disabled?: boolean
  label?: string
}

export function ColorPicker({
  value,
  takenColors,
  exhausted,
  onChange,
  disabled = false,
  label = 'Family colour',
}: ColorPickerProps) {
  const taken = new Set(takenColors.filter((slot) => slot !== value.color))
  const refs = useRef<Array<HTMLButtonElement | null>>([])

  function focusSlot(index: number) {
    const clamped = ((index % PALETTE_SIZE) + PALETTE_SIZE) % PALETTE_SIZE
    refs.current[clamped]?.focus()
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    switch (event.key) {
      case 'ArrowRight':
        event.preventDefault()
        focusSlot(index + 1)
        break
      case 'ArrowLeft':
        event.preventDefault()
        focusSlot(index - 1)
        break
      case 'ArrowDown':
        event.preventDefault()
        focusSlot(index + 6)
        break
      case 'ArrowUp':
        event.preventDefault()
        focusSlot(index - 6)
        break
      default:
        break
    }
  }

  if (exhausted) {
    return (
      <div className="color-picker color-picker--wheel">
        <label className="color-picker__wheel-label" htmlFor="color-picker-wheel">
          {label} — the palette is full, choose any colour
        </label>
        <input
          id="color-picker-wheel"
          type="color"
          className="color-picker__wheel"
          value={value.color_custom ?? '#8A8A8A'}
          disabled={disabled}
          onChange={(event) => onChange({ color: null, color_custom: event.target.value })}
        />
        <p className="color-picker__hint">
          Every one of the 24 palette colours is taken on this trip, so this family gets a
          free choice instead. It will not be tuned for contrast against the others the way
          the palette is.
        </p>
      </div>
    )
  }

  return (
    <div className="color-picker">
      {label ? <span className="color-picker__label">{label}</span> : null}
      <div className="color-picker__grid" role="radiogroup" aria-label={label}>
        {Array.from({ length: PALETTE_SIZE }, (_, i) => i + 1).map((slot, index) => {
          const name = PALETTE_NAMES[index]
          const isTaken = taken.has(slot)
          const isSelected = value.color === slot
          return (
            <button
              key={slot}
              ref={(el) => {
                refs.current[index] = el
              }}
              type="button"
              role="radio"
              aria-checked={isSelected}
              aria-label={isTaken ? `${name} (taken)` : name}
              className={`color-picker__swatch${isSelected ? ' is-selected' : ''}${
                isTaken ? ' is-taken' : ''
              }`}
              style={{ background: `var(--family-${slot})` }}
              disabled={disabled || isTaken}
              tabIndex={isSelected || (!value.color && index === 0) ? 0 : -1}
              onKeyDown={(event) => onKeyDown(event, index)}
              onClick={() => onChange({ color: slot, color_custom: null })}
              title={isTaken ? `${name} — taken` : name}
            >
              {isSelected ? <span className="color-picker__check" aria-hidden="true" /> : null}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** The first slot 1-24 not in `takenColors` — the picker's default pre-selection, so a
 * founder who never touches the grid still submits a valid, uncontested colour
 * (`web/e2e/tests/04-ws-liveness.spec.ts` only fills in a name). `null` when every slot is
 * taken, which is exactly when the caller should be showing the wheel instead. */
export function firstFreeColor(takenColors: number[]): number | null {
  const taken = new Set(takenColors)
  for (let slot = 1; slot <= PALETTE_SIZE; slot += 1) {
    if (!taken.has(slot)) return slot
  }
  return null
}
