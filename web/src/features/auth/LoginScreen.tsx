/**
 * Login (F-3).
 *
 * The heading is the instance's own name from the public `GET /settings`, so a self-hoster
 * sees their household's name before authenticating rather than a generic product page.
 *
 * The server's failure message is deliberately identical for "no such user" and "wrong
 * password"; this screen shows it verbatim and adds nothing that would distinguish them.
 */

import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, api } from '../../app/apiClient'
import { useSession } from '../../app/session'
import type { InstanceSettings } from '../../app/types'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useValidatedField } from '../../app/ui/useValidatedField'
import './auth.css'

const required = (label: string) => (value: string) =>
  value.trim().length === 0 ? `${label} is required.` : null

export default function LoginScreen() {
  const { login, signedOutReason } = useSession()
  const [instance, setInstance] = useState<InstanceSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  /** Seconds left on a 429. While it runs, submit stays disabled. */
  const [waitSeconds, setWaitSeconds] = useState(0)

  const username = useValidatedField(required('Username'))
  const password = useValidatedField(required('Password'))

  useEffect(() => {
    // Public endpoint: no session needed, and a failure here must not block logging in.
    api
      .get<InstanceSettings>('/settings', { signalUnauthorized: false })
      .then(setInstance)
      .catch(() => setInstance(null))
  }, [])

  useEffect(() => {
    if (waitSeconds <= 0) return
    const timer = setTimeout(() => setWaitSeconds((s) => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [waitSeconds])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    // Both validators run before the early return, so a submit with two empty fields
    // marks both rather than only the first.
    const ok = [username.validate(), password.validate()].every(Boolean)
    if (!ok || waitSeconds > 0) return

    setBusy(true)
    try {
      await login(username.value, password.value)
      // On success the session provider re-routes; this component unmounts.
    } catch (cause) {
      if (cause instanceof ApiError) {
        setError(cause.message)
        if (cause.code === 'rate_limited') setWaitSeconds(cause.retryAfter ?? 60)
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
        <h1 className="auth-title">{instance?.instance_name ?? 'Kindred'}</h1>
        <p className="auth-sub">Sign in to plan the trip.</p>

        {error ? <Banner tone="error">{error}</Banner> : null}
        {/* Why they are looking at this screen, when they did not choose to be. */}
        {error === null && signedOutReason ? (
          <Banner tone="info">{signedOutReason}</Banner>
        ) : null}

        <TextField
          label="Username"
          autoComplete="username"
          autoFocus
          error={username.error}
          disabled={busy}
          {...username.inputProps}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          error={password.error}
          disabled={busy}
          {...password.inputProps}
        />

        <Button type="submit" block busy={busy} disabled={waitSeconds > 0}>
          {waitSeconds > 0 ? `Try again in ${waitSeconds}s` : 'Sign in'}
        </Button>

        <p className="auth-foot">
          {instance?.invite_only
            ? 'New here? Ask whoever organises the trip for an invite link.'
            : null}
        </p>
      </form>
    </div>
  )
}
