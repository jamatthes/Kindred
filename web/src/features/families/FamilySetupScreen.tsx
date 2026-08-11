/**
 * `/setup/family` — name your family on first login (FM-13).
 *
 * Rendered whenever the server's `next_step` is `setup_family`: the state a new family's head
 * is in from the moment they accept a `create_family` invite until they finish here, and — as
 * of 2026-08-11 — the state the **owner** is in between naming the trip and entering the app.
 * Outside the app shell for the same reason the join screen is: they are not on the trip yet,
 * and nothing else is reachable — **not because the UI hides it, but because the server
 * refuses**. This screen carries its own log-out action, since there is no nav rail to hold
 * one.
 *
 * The copy is deliberately not branched on who the caller is. It never says "you were
 * invited", so it is true for the owner, who arrives here from their own trip-setup screen
 * rather than from a link; and "You will be this family's head" is exactly as true for them,
 * because owning the trip and heading a family are independent things (`plan/overview.md` >
 * Roles). A screen that explained the difference would be teaching the distinction at the one
 * moment it does not matter.
 *
 * Abandoning it costs nothing. Nothing is written until submit, and `next_step` is derived
 * from stored state, so the next login lands right back here with nothing stale to reconcile.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../app/apiClient'
import { useSession } from '../../app/session'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useValidatedField } from '../../app/ui/useValidatedField'
import { familiesApi } from './api'
import '../auth/auth.css'

export function FamilySetupScreen() {
  const { user, logout, refresh } = useSession()
  const [address, setAddress] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const name = useValidatedField((value) =>
    value.trim().length === 0 ? 'Your family needs a name.' : null,
  )

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.validate()) return
    setBusy(true)
    setError(null)
    try {
      await familiesApi.createMine({
        name: name.value.trim(),
        ...(address.trim() ? { home_address: address.trim() } : {}),
      })
      // `next_step` becomes `app` on the server; re-reading it is what moves the shell on.
      await refresh()
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'name_taken') {
        // On the field, not as a toast — it is that field's problem and that field's fix.
        name.setError(cause.message)
      } else if (cause instanceof ApiError && cause.code === 'already_has_family') {
        // A double submit whose first attempt actually succeeded. Treat it as success and
        // re-read the gate, which is what the design's edge-case table asks for.
        await refresh()
        return
      } else if (cause instanceof ApiError) {
        setError(cause.message)
      } else {
        setError('Your family could not be created. Try again.')
      }
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="auth-wordmark">Kindred</div>
        <h1 className="auth-title">Name your family</h1>
        <p className="auth-sub">
          You can invite the rest of them next.
          {user?.trip ? ` This is for ${user.trip.name}.` : null}
        </p>

        {error ? <Banner tone="error">{error}</Banner> : null}

        <TextField
          label="Family name"
          autoFocus
          placeholder="The Parkers"
          error={name.error}
          disabled={busy}
          {...name.inputProps}
        />

        <TextField
          label="Home address"
          value={address}
          disabled={busy}
          hint="Optional — you can add this later. We use it to show travel times."
          onChange={(event) => setAddress(event.target.value)}
        />

        <p className="auth-note">
          You will be this family&apos;s head. You can rename the family and hand that role on
          later.
        </p>

        <Button type="submit" block busy={busy}>
          Create family
        </Button>

        {/* The nav rail that normally holds this is not rendered here. */}
        <button type="button" className="auth-link" onClick={() => void logout()}>
          Log out
        </button>
      </form>
    </div>
  )
}
