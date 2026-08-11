/**
 * `/join/<token>` — accept an invite and register (FM-7, FM-8).
 *
 * Outside the app shell: no nav rail, no tabs, because the visitor is not yet a member and a
 * shell full of controls they cannot use would be a lie about where they are.
 *
 * **The preview is fetched and rendered before anything is asked for.** Someone should learn
 * which trip and which family they are joining — or that the link is dead — before they type
 * a password. An invalid token gets one plain card and no trip details at all: the server
 * sends nothing but the instance name, so there is nothing here to leak even by accident.
 */

import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../app/apiClient'
import { useSession } from '../../app/session'
import { useNavigate } from '../../app/router'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useValidatedField } from '../../app/ui/useValidatedField'
import type { InvitePreview } from '../../app/types'
import { invitesApi } from './api'
import '../auth/auth.css'

/** Plain words for each reason the server may give. Never a code, never a status number. */
const INVALID_REASON: Record<string, string> = {
  unknown: 'This invite link is no longer valid.',
  expired: 'This invite link has expired.',
  used: 'This invite link has already been used.',
  revoked: 'This invite link was withdrawn.',
  trip_ended: 'This trip has finished, so there is nothing left to join.',
  family_missing: 'The family this invite was for is no longer on the trip.',
}

const required = (label: string) => (value: string) =>
  value.trim().length === 0 ? `${label} is required.` : null

export function JoinScreen({ token }: { token: string }) {
  const { user, adoptUser, logout } = useSession()
  const navigate = useNavigate()
  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const firstName = useValidatedField(required('First name'))
  const lastName = useValidatedField()
  const username = useValidatedField(required('Username'))
  const password = useValidatedField(required('Password'))
  const confirm = useValidatedField((value) =>
    value !== password.value ? 'Those passwords do not match.' : null,
  )

  useEffect(() => {
    invitesApi
      .preview(token)
      .then(setPreview)
      .catch(() => setError('We could not check that link. Try again in a moment.'))
      .finally(() => setLoading(false))
  }, [token])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    // Every validator runs before the early return, so a submit with three empty fields
    // marks all three rather than only the first.
    const ok = [
      firstName.validate(),
      username.validate(),
      password.validate(),
      confirm.validate(),
    ].every(Boolean)
    if (!ok) return

    setBusy(true)
    try {
      const result = await invitesApi.accept(token, {
        username: username.value.trim(),
        first_name: firstName.value.trim(),
        last_name: lastName.value.trim(),
        password: password.value,
        password_confirm: confirm.value,
      })
      // The response already carries the new user and the gate's answer, so adopting it is
      // enough — re-fetching `auth/me` would be a round trip spent confirming what we were
      // just told. The session's route then sends them to the app or to family setup.
      adoptUser(result.user)
      navigate(result.next_step === 'setup_family' ? { name: 'setup-family' } : { name: 'home' }, {
        replace: true,
      })
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'username_taken') {
        username.setError(cause.message)
      } else if (cause instanceof ApiError) {
        setError(cause.message)
      } else {
        setError('Something went wrong. Try again.')
      }
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <p className="auth-sub">Checking your invite…</p>
        </div>
      </div>
    )
  }

  if (error && !preview) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <Banner tone="error">{error}</Banner>
        </div>
      </div>
    )
  }

  if (!preview?.valid) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <div className="auth-wordmark">Kindred</div>
          <h1 className="auth-title">{preview?.instance_name ?? 'Kindred'}</h1>
          <p className="auth-sub">
            {INVALID_REASON[preview?.reason ?? 'unknown'] ?? INVALID_REASON.unknown}
          </p>
          <p className="auth-foot">Ask whoever invited you for a new link.</p>
        </div>
      </div>
    )
  }

  // FM-8: say what will happen rather than silently switching accounts.
  if (user) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <div className="auth-wordmark">Kindred</div>
          <h1 className="auth-title">{preview.instance_name}</h1>
          <p className="auth-sub">
            You are signed in as {user.display_name}. Accepting this invite creates a separate
            account, so you would need to log out first.
          </p>
          <Button
            block
            onClick={async () => {
              await logout()
            }}
          >
            Log out and continue
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="auth-wordmark">Kindred</div>
        <h1 className="auth-title">{preview.instance_name}</h1>
        <p className="auth-sub">
          {preview.mode === 'create_family'
            ? `You're joining ${preview.trip_name} and will create a new family.`
            : // No article: family names usually carry their own ("The Jiangs").
              `You're joining ${preview.family_name} on ${preview.trip_name}.`}
        </p>

        {error ? <Banner tone="error">{error}</Banner> : null}

        <TextField
          label="First name"
          autoComplete="given-name"
          autoFocus
          error={firstName.error}
          disabled={busy}
          {...firstName.inputProps}
        />
        <TextField
          label="Last name (optional)"
          autoComplete="family-name"
          hint="Leave it blank if you go by one name."
          disabled={busy}
          {...lastName.inputProps}
        />
        <TextField
          label="Username"
          autoComplete="username"
          error={username.error}
          disabled={busy}
          {...username.inputProps}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="new-password"
          error={password.error}
          disabled={busy}
          {...password.inputProps}
        />
        <TextField
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          error={confirm.error}
          disabled={busy}
          {...confirm.inputProps}
        />

        <Button type="submit" block busy={busy}>
          Join the trip
        </Button>
      </form>
    </div>
  )
}
