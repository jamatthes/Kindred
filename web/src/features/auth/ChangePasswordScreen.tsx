/**
 * The forced password change (F-5).
 *
 * Reached automatically whenever `must_change_password` is true, from any route, and there
 * is no way past it: the session's routing rule returns this screen for every path until
 * the server says otherwise. There is no nav rail and no tab bar — only the form and a way
 * to log out.
 *
 * The rules are stated before submission rather than discovered by failing.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../app/apiClient'
import { useSession } from '../../app/session'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import { useValidatedField } from '../../app/ui/useValidatedField'
import './auth.css'

const MIN_LENGTH = 10

function validateCurrent(value: string): string | null {
  return value.length === 0 ? 'Enter your current password.' : null
}

function validateNew(value: string): string | null {
  if (value.length === 0) return 'Choose a new password.'
  if (value.length < MIN_LENGTH) return `Use at least ${MIN_LENGTH} characters.`
  return null
}

export default function ChangePasswordScreen() {
  const { user, changePassword, logout } = useSession()
  const toast = useToast()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const current = useValidatedField(validateCurrent)
  const next = useValidatedField(validateNew)
  const confirm = useValidatedField((value) =>
    value === next.value ? null : 'The two passwords do not match.',
  )

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    const ok = [current.validate(), next.validate(), confirm.validate()].every(Boolean)
    if (!ok) return

    setBusy(true)
    try {
      await changePassword(current.value, next.value)
      // The session refresh flips `must_change_password` and the router lands on home.
      toast('Password changed')
    } catch (cause) {
      if (cause instanceof ApiError) {
        // The server blames a specific field where it can; put the message there rather
        // than in a banner the user has to map back onto an input themselves.
        if (cause.code === 'invalid_credentials') current.setError(cause.message)
        else if (cause.code === 'password_unchanged') next.setError(cause.message)
        else if (cause.code === 'validation_error')
          next.setError(cause.fieldError('new_password') ?? cause.message)
        else setError(cause.message)
      } else {
        setError('Something went wrong. Try again.')
      }
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={onSubmit} noValidate>
        <div className="auth-wordmark">Kindred</div>
        <h1 className="auth-title">Choose a new password</h1>
        <p className="auth-sub">
          {user ? `${user.display_name}, your` : 'Your'} account still has the password it was
          set up with, so everyone who saw the setup notes knows it. Pick your own to carry on.
        </p>

        {error ? <Banner tone="error">{error}</Banner> : null}

        <ul className="auth-rules">
          <li>At least {MIN_LENGTH} characters</li>
          <li>Different from your current password</li>
        </ul>

        <TextField
          label="Current password"
          type="password"
          autoComplete="current-password"
          autoFocus
          error={current.error}
          disabled={busy}
          {...current.inputProps}
        />
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          error={next.error}
          disabled={busy}
          {...next.inputProps}
        />
        <TextField
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          error={confirm.error}
          disabled={busy}
          {...confirm.inputProps}
        />

        <Button type="submit" block busy={busy}>
          Save and continue
        </Button>

        <p className="auth-foot">
          Not you?{' '}
          <button type="button" className="auth-linkbtn" onClick={() => void logout()}>
            Log out
          </button>
        </p>
      </form>
    </div>
  )
}
