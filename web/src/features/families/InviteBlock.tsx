/**
 * Invites (FM-5, FM-6).
 *
 * The link is shown **once**. That is not a UI convention, it is what the server does: only
 * the sha256 is stored, so the raw token genuinely cannot be fetched again. The copy says so
 * plainly rather than implying it, because someone who closes this card believing they can
 * come back for the link has lost it.
 *
 * "Invite a new family" is visually separated from the per-family invite, because the two do
 * very different things and only one of them is an organiser's to hand out.
 */

import { useEffect, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button, Spinner } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import type { Invite, InviteCreated } from '../../app/types'
import { invitesApi } from './api'
import { EXPIRY_CHOICES, INVITE_STATUS_LABEL, expiryLabel, relativeTime } from './labels'

function CopyOnce({ created }: { created: InviteCreated }) {
  const toast = useToast()
  return (
    <div className="invite-once">
      <div className="invite-once__row">
        <code>{created.url}</code>
        <Button
          variant="secondary"
          onClick={() => {
            void navigator.clipboard?.writeText(created.url)
            // A transient confirmation of the user's own action — exactly what a toast is
            // for, and the only thing this screen uses one for.
            toast('Invite link copied.')
          }}
        >
          Copy
        </Button>
      </div>
      <p className="invite-once__note">
        Expires {relativeTime(created.expires_at)} · shown only now, and it cannot be
        retrieved later.
      </p>
    </div>
  )
}

/**
 * The organiser's separate action: whoever opens this link founds their own family.
 *
 * As of 2026-08-11 it is also the *only* way an organiser brings a family onto the trip. The
 * card used to carry a second action, `Or add one myself`, over the bare `POST /families` —
 * which made a family with nobody in it and left the organiser outside what they had just
 * created. Both the action and the route are gone (FM-1).
 */
export function NewFamilyInviteCard() {
  const [created, setCreated] = useState<InviteCreated | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function create() {
    setBusy(true)
    setError(null)
    try {
      setCreated(await invitesApi.create({ family_id: null, expires_in_hours: 168 }))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That invite could not be created.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fcard fcard--invite">
      <div className="fcard__head">
        <span className="fcard__plus" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </span>
        <span className="fcard__name">Invite a family</span>
      </div>
      <p className="fcard__blurb">
        Whoever opens this link creates their own family and joins the trip. Organisers only.
      </p>
      {error ? <Banner tone="error">{error}</Banner> : null}
      {created ? (
        <CopyOnce created={created} />
      ) : (
        <div className="panel-block__actions">
          <Button variant="secondary" onClick={() => void create()} busy={busy}>
            Create a link
          </Button>
        </div>
      )}
    </div>
  )
}

/** The per-family block: create a link into *this* family, and manage outstanding ones. */
export function InviteBlock({
  familyId,
  editable,
}: {
  familyId: string
  editable: boolean
}) {
  const toast = useToast()
  const [invites, setInvites] = useState<Invite[] | null>(null)
  const [created, setCreated] = useState<InviteCreated | null>(null)
  const [expiry, setExpiry] = useState<(typeof EXPIRY_CHOICES)[number]>(168)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    invitesApi
      .list(familyId)
      .then((next) => {
        if (!cancelled) setInvites(next)
      })
      .catch(() => {
        // A member who may not list invites gets a 403 here. That is not an error worth
        // showing — the block simply has nothing to offer them.
        if (!cancelled) setInvites([])
      })
    return () => {
      cancelled = true
    }
  }, [familyId])

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const next = await invitesApi.create({ family_id: familyId, expires_in_hours: expiry })
      setCreated(next)
      setInvites(await invitesApi.list(familyId))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That invite could not be created.')
    } finally {
      setBusy(false)
    }
  }

  async function revoke(invite: Invite) {
    const previous = invites
    setInvites((current) =>
      (current ?? []).map((i) => (i.id === invite.id ? { ...i, status: 'revoked' } : i)),
    )
    try {
      await invitesApi.revoke(invite.id)
      // Reversible by reissuing, so undo rather than a confirm dialog.
      toast('Invite revoked.')
    } catch (cause) {
      setInvites(previous)
      setError(cause instanceof ApiError ? cause.message : 'That invite could not be revoked.')
    }
  }

  if (!editable) return null

  return (
    <section className="panel-block">
      <h3 className="panel-block__title">Invites</h3>
      {error ? <Banner tone="error">{error}</Banner> : null}

      {created ? (
        <CopyOnce created={created} />
      ) : (
        <div className="invite-form">
          <label className="invite-form__expiry">
            <span>Link expires after</span>
            <select
              value={expiry}
              onChange={(event) =>
                setExpiry(Number(event.target.value) as (typeof EXPIRY_CHOICES)[number])
              }
            >
              {EXPIRY_CHOICES.map((hours) => (
                <option key={hours} value={hours}>
                  {expiryLabel(hours)}
                </option>
              ))}
            </select>
          </label>
          <Button onClick={() => void create()} busy={busy}>
            Invite someone
          </Button>
        </div>
      )}

      {invites === null ? (
        <Spinner />
      ) : invites.length === 0 ? (
        <p className="panel-block__body muted">No open invites.</p>
      ) : (
        <ul className="invite-list">
          {invites.map((invite) => (
            <li key={invite.id} className="invite-list__row">
              <span className={`chip chip--${invite.status}`}>
                {INVITE_STATUS_LABEL[invite.status]}
              </span>
              <span className="invite-list__meta">
                {invite.created_by_name ? `from ${invite.created_by_name} · ` : null}
                {invite.status === 'active'
                  ? `expires ${relativeTime(invite.expires_at)}`
                  : invite.used_by_name
                    ? `used by ${invite.used_by_name}`
                    : `expired ${relativeTime(invite.expires_at)}`}
              </span>
              {invite.status === 'active' ? (
                <Button variant="ghost" onClick={() => void revoke(invite)}>
                  Revoke
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
