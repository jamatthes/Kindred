/**
 * A time of day on the itinerary's grid.
 *
 * Typing is the fast path and the base: "14:30", "2.30pm", "1430", "9am" all land, and the
 * value the caller sees is always 24-hour `HH:MM`. The list is the touch path — a scrolling
 * column of every slot on the grid, which is a wheel in everything but implementation and,
 * unlike a real wheel, is a `listbox` a screen reader can read and a keyboard can drive.
 *
 * Everything snaps to `--daytrack-snap` (15 minutes, mirrored in `design/snap.ts`), because
 * the itinerary day track can only *draw* a bar on a grid line. A field that accepted 14:37
 * would be promising a precision the next screen silently rounds away.
 */

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { DAYTRACK_SNAP_MINUTES } from '../../../design/snap'
import { formatTime, isIsoTime, minutesOf, parseTypedTime, snapTime, timeOf, timeOptions } from './calendar'
import type { IsoTime } from './calendar'
import './pickers.css'

export type TimeFieldProps = {
  label: string
  value: IsoTime | ''
  onChange: (value: IsoTime | '') => void
  /** Minutes per step. Defaults to the itinerary grid; a caller with its own grid may differ. */
  step?: number
  error?: string | null
  hint?: ReactNode
  disabled?: boolean
  name?: string
}

const TYPING_HELP = 'Enter a time like 14:30 or 2.30pm.'

export function TimeField({
  label,
  value,
  onChange,
  step = DAYTRACK_SNAP_MINUTES,
  error,
  hint,
  disabled = false,
  name,
}: TimeFieldProps) {
  const id = useId()
  const [text, setText] = useState(value)
  const [typingError, setTypingError] = useState<string | null>(null)
  const [listOpen, setListOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)

  // The field is controlled from outside while it is not being typed in; once the caller's
  // value changes (a preset, a reset) the text catches up.
  useEffect(() => {
    setText(value)
  }, [value])

  const options = timeOptions(step)
  /* The list always has exactly one focusable option, so it is reachable by keyboard even
     before a value exists — an empty field would otherwise open a list Tab skips over. */
  const activeOption = isIsoTime(value) ? snapTime(value, step) : options[0]
  const shownError = error ?? typingError
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const described = [shownError ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ')

  const commit = useCallback(
    (raw: string) => {
      if (raw.trim() === '') {
        setTypingError(null)
        onChange('')
        return
      }
      const parsed = parseTypedTime(raw)
      if (!parsed) {
        // Rejected, not guessed. The old text stays put so the typist can see what they wrote.
        setTypingError(TYPING_HELP)
        return
      }
      const snapped = snapTime(parsed, step)
      setTypingError(null)
      setText(snapped)
      onChange(snapped)
    },
    [onChange, step],
  )

  /** ↑/↓ nudge by one grid step — the same gesture the day track's bars use. */
  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Enter') {
        event.preventDefault()
        commit(text)
        return
      }
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
      event.preventDefault()
      const base = isIsoTime(value) ? value : (parseTypedTime(text) ?? '09:00')
      const delta = event.key === 'ArrowUp' ? step : -step
      const next = timeOf(minutesOf(snapTime(base, step)) + delta)
      setTypingError(null)
      setText(next)
      onChange(next)
    },
    [commit, onChange, step, text, value],
  )

  // Opening the list scrolls the current time into view; a list that opens at midnight when
  // the value is 6pm is a list nobody scrolls to the end of.
  useEffect(() => {
    if (!listOpen) return
    const target = listRef.current?.querySelector<HTMLElement>('[tabindex="0"]')
    target?.scrollIntoView?.({ block: 'center' })
    target?.focus()
  }, [listOpen])

  return (
    <div className={`k-field k-picker-time${shownError ? ' k-field--error' : ''}`}>
      <label className="k-field__label" htmlFor={id}>
        {label}
      </label>
      <div className="k-picker-field__row">
        <input
          id={id}
          name={name}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          className="k-field__input k-picker-field__input"
          value={text}
          disabled={disabled}
          placeholder=" "
          aria-invalid={shownError ? true : undefined}
          aria-describedby={described || undefined}
          onChange={(event) => setText(event.target.value)}
          onBlur={(event) => commit(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button
          type="button"
          className="k-picker-field__button"
          aria-label={`${label} — choose from the list`}
          aria-expanded={listOpen}
          aria-haspopup="listbox"
          disabled={disabled}
          onClick={() => setListOpen((open) => !open)}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
        </button>
      </div>

      {listOpen ? (
        <div
          className="k-picker-time__list"
          role="listbox"
          aria-label={label}
          ref={listRef}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault()
              setListOpen(false)
              return
            }
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
            event.preventDefault()
            // Roving focus down the column — the keyboard equivalent of spinning the wheel.
            const items = [...(listRef.current?.querySelectorAll<HTMLElement>('[role="option"]') ?? [])]
            const index = items.indexOf(document.activeElement as HTMLElement)
            const next = items[index + (event.key === 'ArrowDown' ? 1 : -1)]
            next?.focus()
          }}
        >
          {options.map((option) => (
            <button
              key={option}
              type="button"
              role="option"
              aria-selected={option === value}
              tabIndex={option === activeOption ? 0 : -1}
              className={`k-picker-time__option${option === value ? ' k-picker-time__option--selected' : ''}`}
              onClick={() => {
                setTypingError(null)
                setText(option)
                onChange(option)
                setListOpen(false)
              }}
            >
              {formatTime(option)}
            </button>
          ))}
        </div>
      ) : null}

      {shownError ? (
        <span className="k-field__error" id={errorId} role="alert">
          {shownError}
        </span>
      ) : null}
      {hint ? (
        <span className="k-field__hint" id={hintId}>
          {hint}
        </span>
      ) : null}
    </div>
  )
}
