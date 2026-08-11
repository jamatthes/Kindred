/**
 * The home address block (FM-3) — four states, a confirmation step, and a retry.
 *
 * The states have different text, different icons and different next actions, and are never
 * distinguished by colour alone. The distinction that matters most is `not_found` vs `error`:
 * "check what you typed" and "try again later" send the user to different places, and the
 * server keeps them apart precisely so this component can.
 *
 * Only a caller entitled to the address gets the editable form. Entitlement is read from the
 * response rather than computed: the server omits `home_address` entirely for someone who may
 * not see it, so `'home_address' in family` *is* the answer — no role check needed, and none
 * that could disagree with the server.
 */

import { useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import type { FamilyDetail } from '../../app/types'
import { familiesApi } from './api'
import { GEOCODE_STATE } from './labels'

function StateIcon({ status }: { status: FamilyDetail['geocode_status'] }) {
  const common = {
    width: 15,
    height: 15,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    'aria-hidden': true,
  } as const
  if (status === 'ok')
    return (
      <svg {...common}>
        <path d="M12 21s7-6.3 7-11a7 7 0 1 0-14 0c0 4.7 7 11 7 11z" />
        <circle cx="12" cy="10" r="2.6" />
      </svg>
    )
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6M12 16.5h.01" />
    </svg>
  )
}

export function HomeAddressBlock({
  family,
  editable,
  onChanged,
}: {
  family: FamilyDetail
  editable: boolean
  onChanged: (next: FamilyDetail) => void
}) {
  const toast = useToast()
  // `undefined` means the server withheld it; `null` means there is none. The two must not
  // be collapsed — one is a privacy decision and the other is an empty field.
  const entitled = 'home_address' in family
  const [draft, setDraft] = useState(family.home_address ?? '')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** The just-geocoded result, awaiting "Looks right" before the block settles. */
  const [confirming, setConfirming] = useState(false)

  if (!entitled) {
    return (
      <section className="panel-block">
        <h3 className="panel-block__title">Home</h3>
        <p className="panel-block__body">
          {family.home_locality
            ? `${family.home_locality} — the full address is visible to this family only.`
            : 'No home town set yet.'}
        </p>
      </section>
    )
  }

  const state = GEOCODE_STATE[family.geocode_status]

  async function save() {
    if (!draft.trim()) return
    setBusy(true)
    setError(null)
    try {
      const next = await familiesApi.setHome(family.id, draft.trim())
      onChanged(next)
      setEditing(false)
      // Confirmation step: the coordinate is not treated as final until the user agrees the
      // geocoder found the right place (FM-3).
      setConfirming(next.geocode_status === 'ok')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That address could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  async function retry() {
    setBusy(true)
    setError(null)
    try {
      onChanged(await familiesApi.retryGeocode(family.id))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That address could not be placed.')
    } finally {
      setBusy(false)
    }
  }

  async function clear() {
    setBusy(true)
    try {
      await familiesApi.clearHome(family.id)
      onChanged({
        ...family,
        home_address: null,
        home_locality: null,
        home_placed: false,
        geocode_status: 'pending',
        geocode_error: null,
      })
      setDraft('')
      toast('Home address removed.')
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <section className="panel-block">
        <h3 className="panel-block__title">Home</h3>
        {error ? <Banner tone="error">{error}</Banner> : null}
        <TextField
          label="Home address"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          hint="Free text — we look it up once and remember where it is."
          disabled={busy}
        />
        <div className="panel-block__actions">
          <Button onClick={() => void save()} busy={busy}>
            Save
          </Button>
          <Button variant="ghost" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
          </Button>
        </div>
      </section>
    )
  }

  return (
    <section className="panel-block">
      <h3 className="panel-block__title">Home</h3>

      {confirming && family.home_placed ? (
        <div className="confirm-block">
          <p className="confirm-block__found">
            <StateIcon status="ok" />
            We found: <strong>{family.home_address}</strong>
            {family.home_locality ? ` (${family.home_locality})` : null}
          </p>
          <div className="panel-block__actions">
            <Button onClick={() => setConfirming(false)}>Looks right</Button>
            <Button
              variant="secondary"
              onClick={() => {
                setConfirming(false)
                setEditing(true)
              }}
            >
              Edit
            </Button>
          </div>
        </div>
      ) : (
        <>
          <p className="panel-block__state">
            <StateIcon status={family.geocode_status} />
            <span>
              <strong>{family.geocode_status === 'ok' ? family.home_address : state.title}</strong>
              {family.geocode_status === 'ok' ? (
                family.home_locality ? <span className="muted"> · {family.home_locality}</span> : null
              ) : (
                <span className="muted"> {state.body}</span>
              )}
            </span>
          </p>

          {family.geocode_error === 'no_api_key' ? (
            <p className="panel-block__body muted">
              No mapping key is configured for this instance. The trip organiser can set one up
              in the admin console.
            </p>
          ) : null}

          {error ? <Banner tone="error">{error}</Banner> : null}

          {editable ? (
            <div className="panel-block__actions">
              <Button variant="secondary" onClick={() => setEditing(true)} disabled={busy}>
                {family.home_address ? 'Change address' : 'Add an address'}
              </Button>
              {state.canRetry ? (
                <Button variant="ghost" onClick={() => void retry()} busy={busy}>
                  Try again
                </Button>
              ) : null}
              {family.home_address ? (
                <Button variant="ghost" onClick={() => void clear()} disabled={busy}>
                  Remove
                </Button>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </section>
  )
}
