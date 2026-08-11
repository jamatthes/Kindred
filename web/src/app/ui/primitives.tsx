/**
 * Form and feedback primitives. Every screen in the app is built from these, so the six
 * field states, the error placement and the spinner rules are decided once here rather
 * than re-litigated per form.
 */

import { useId } from 'react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, Ref } from 'react'
import './ui.css'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** `danger` is for admin-destructive confirms only — it is not a colour choice. */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  block?: boolean
  /** Shows an inline spinner and disables the button — for sub-second waits. */
  busy?: boolean
  /** React 19 passes `ref` as an ordinary prop; declared so callers can focus a button. */
  ref?: Ref<HTMLButtonElement>
}

export function Button({
  variant = 'primary',
  block = false,
  busy = false,
  disabled,
  children,
  className,
  ...rest
}: ButtonProps) {
  const classes = ['k-btn', `k-btn--${variant}`, block ? 'k-btn--block' : '', className ?? '']
    .filter(Boolean)
    .join(' ')
  return (
    <button className={classes} disabled={disabled || busy} {...rest}>
      {busy ? <span className="k-spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  )
}

type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> & {
  label: string
  /** Shown beneath the field, below the error when both are present. */
  hint?: ReactNode
  error?: string | null
}

export function TextField({ label, hint, error, ...rest }: TextFieldProps) {
  const id = useId()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ')

  return (
    <div className={`k-field${error ? ' k-field--error' : ''}`}>
      <label className="k-field__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="k-field__input"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        /* A placeholder of " " keeps :not(:placeholder-shown) usable as the "filled"
           state without printing placeholder text the design does not ask for. */
        placeholder={rest.placeholder ?? ' '}
        {...rest}
      />
      {error ? (
        <span className="k-field__error" id={errorId} role="alert">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v6M12 16.5h.01" />
          </svg>
          {error}
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

export function Spinner() {
  return <span className="k-spinner" role="status" aria-label="Working" />
}

export function Banner({
  tone = 'error',
  children,
}: {
  tone?: 'error' | 'info'
  children: ReactNode
}) {
  return (
    <div className={`k-banner k-banner--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}

export function Skeleton({ width, height }: { width?: string; height: string }) {
  return <div className="k-skeleton" style={{ width: width ?? '100%', height }} aria-hidden="true" />
}
