/**
 * One labelled date input with a calendar button — the shared body of `DatePicker` and each
 * half of `DateRangePicker`.
 *
 * **Typed entry is the base; the calendar is the enhancement.** The control the label points
 * at is a real input that types and submits, and the calendar button is a second, optional
 * way to fill it. Which is why the browser's own picker indicator is suppressed in CSS: two
 * calendars on one field is how the observed bug arrived: ours opens at the trip's start
 * month, the browser's opens wherever it likes.
 *
 * Two entry modes, decided by feature detection rather than by a user-agent guess:
 *
 *  - `native` — `<input type="date">`. Preferred wherever it exists: the OS keyboard on a
 *    phone, the locale's own segment order, the browser's own sanitising, and a value that
 *    is already ISO. There is nothing here we would do better by hand.
 *  - `text` — the fallback, and the only place our own parser runs. It accepts what people
 *    actually type (`4/12/2027`, `04.12.27`, `2027-12-04`) and *rejects* anything else with
 *    the shape it wanted, rather than coercing it into some date the trip does not want.
 *
 * The mode is exposed as a prop so both branches are testable; nothing in the app sets it.
 */

import { useEffect, useId, useState } from 'react'
import type { ReactNode } from 'react'
import { isIsoDate, parseTypedDate } from './calendar'
import type { IsoDate } from './calendar'

export type DateEntryMode = 'auto' | 'native' | 'text'

export type DateFieldProps = {
  label: string
  value: IsoDate | ''
  onChange: (value: IsoDate | '') => void
  min?: IsoDate | null
  max?: IsoDate | null
  error?: string | null
  hint?: ReactNode
  disabled?: boolean
  name?: string
  /** Rendered when the calendar button is pressed; the caller owns the open state. */
  open?: boolean
  onToggle?: () => void
  children?: ReactNode
  /** Extra id(s) for `aria-describedby` — used for the range's coupling explanation. */
  describedBy?: string
  entryMode?: DateEntryMode
}

const TYPING_HELP = 'Enter a date as DD/MM/YYYY.'

/** Does this browser give us a real date input? Asked once, of the DOM, not of the UA string. */
export function supportsNativeDate(): boolean {
  if (typeof document === 'undefined') return false
  const probe = document.createElement('input')
  probe.setAttribute('type', 'date')
  return probe.type === 'date'
}

export function DateField({
  label,
  value,
  onChange,
  min,
  max,
  error,
  hint,
  disabled,
  name,
  open = false,
  onToggle,
  children,
  describedBy,
  entryMode = 'auto',
}: DateFieldProps) {
  const id = useId()
  const [typingError, setTypingError] = useState<string | null>(null)
  const [text, setText] = useState<string>(value)
  const mode: 'native' | 'text' =
    entryMode === 'auto' ? (supportsNativeDate() ? 'native' : 'text') : entryMode

  // The field is controlled from outside; when the caller's value moves (a calendar click, a
  // preset, a cleared end date) the text catches up.
  useEffect(() => {
    setText(value)
    setTypingError(null)
  }, [value])

  const shownError = error ?? typingError
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const described = [shownError ? errorId : null, hint ? hintId : null, describedBy]
    .filter(Boolean)
    .join(' ')

  function commit(raw: string) {
    if (raw.trim() === '') {
      setTypingError(null)
      onChange('')
      return
    }
    const parsed = isIsoDate(raw) ? raw : parseTypedDate(raw)
    if (!parsed) {
      // Rejected, not guessed, and the typed text stays put so it can be corrected.
      setTypingError(TYPING_HELP)
      return
    }
    setTypingError(null)
    onChange(parsed)
  }

  const shared = {
    id,
    name,
    className: 'k-field__input k-picker-field__input',
    disabled,
    placeholder: ' ',
    'aria-invalid': shownError ? (true as const) : undefined,
    'aria-describedby': described || undefined,
  }

  return (
    <div className={`k-field k-picker-field${shownError ? ' k-field--error' : ''}`}>
      <label className="k-field__label" htmlFor={id}>
        {label}
      </label>
      <div className="k-picker-field__row">
        {mode === 'native' ? (
          <input
            {...shared}
            type="date"
            value={value}
            min={min ?? undefined}
            max={max ?? undefined}
            onChange={(event) => commit(event.target.value)}
          />
        ) : (
          <input
            {...shared}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            value={text}
            onChange={(event) => {
              setText(event.target.value)
              setTypingError(null)
            }}
            onBlur={(event) => commit(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return
              event.preventDefault()
              commit(text)
            }}
          />
        )}
        <button
          type="button"
          className="k-picker-field__button"
          aria-label={`${label} — open calendar`}
          aria-expanded={open}
          aria-haspopup="dialog"
          disabled={disabled}
          onClick={onToggle}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <rect x="3" y="5" width="18" height="16" rx="2" />
            <path d="M3 10h18M8 3v4M16 3v4" />
          </svg>
        </button>
        {children}
      </div>
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
