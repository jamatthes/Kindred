/**
 * The profile page (FM-11, FM-14). One page, available in **every** stage, including End —
 * a name, a face, a password and a theme are account properties, not trip data.
 *
 * The location toggle is the part worth reading twice. It is shown even when the family's
 * settings are currently hiding this person, with an explanation of who to ask — never
 * disabled, never silently ineffective. Someone else's decision may stop their marker
 * appearing; it must not stop them expressing their own choice, and the one direction that
 * always matters — turning it off — is never blocked by anything.
 */

import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { useSession } from '../../app/session'
import { Banner, Button, Spinner, TextField } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import { IdentityBadge } from '../../design/IdentityBadge'
import type { FamilyDetail } from '../../app/types'
import { familiesApi, profileApi } from './api'
import { ROLE_LABEL } from './labels'
import './families.css'

/** Stated before the picker opens, not only on failure. */
const ACCEPTED = 'JPEG, PNG or WebP, up to 8MB.'

function AvatarBlock() {
  const { user, adoptUser } = useSession()
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const [chosen, setChosen] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Object URLs are a resource, not a string: not revoking them leaks the decoded image for
  // as long as the tab lives.
  useEffect(() => {
    if (!chosen) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(chosen)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [chosen])

  if (!user) return null

  async function save() {
    if (!chosen) return
    setBusy(true)
    setError(null)
    try {
      adoptUser(await profileApi.uploadAvatar(chosen))
      setChosen(null)
      toast('Profile picture updated.')
    } catch (cause) {
      // The specific cause, never a generic "upload failed": format, size and unreadable are
      // three different problems with three different fixes.
      setError(cause instanceof ApiError ? cause.message : 'That picture could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    try {
      adoptUser(await profileApi.removeAvatar())
      toast('Profile picture removed.')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That picture could not be removed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel-block">
      <h3 className="panel-block__title">Picture</h3>
      {error ? <Banner tone="error">{error}</Banner> : null}

      <div className="profile-avatar">
        {previewUrl ? (
          // The square crop the server will apply, previewed. Centre-square and not
          // adjustable in v1 — a cropper is a component this product needs nowhere else.
          <span className="profile-avatar__preview">
            <img src={previewUrl} alt="Your new profile picture" />
          </span>
        ) : (
          <IdentityBadge
            initials={user.initials}
            familyColor={user.family?.color}
            avatarUrl={user.avatar_url}
            avatarThumbUrl={user.avatar_thumb_url}
            size={64}
            name={user.display_name}
          />
        )}

        <div className="profile-avatar__actions">
          <input
            ref={input}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={(event) => setChosen(event.target.files?.[0] ?? null)}
          />
          {chosen ? (
            <>
              <Button onClick={() => void save()} busy={busy}>
                Save
              </Button>
              <Button variant="ghost" onClick={() => setChosen(null)} disabled={busy}>
                Choose another
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" onClick={() => input.current?.click()}>
                Upload a photo
              </Button>
              {user.avatar_url ? (
                <Button variant="ghost" onClick={() => void remove()} disabled={busy}>
                  Remove photo
                </Button>
              ) : null}
            </>
          )}
          <p className="panel-block__body muted">{ACCEPTED}</p>
        </div>
      </div>
    </section>
  )
}

function NameBlock() {
  const { user, adoptUser } = useSession()
  const toast = useToast()
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState({
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
    display_name: user?.display_name ?? '',
  })

  if (!user) return null
  const current = user

  async function saveField(field: keyof typeof draft) {
    const value = draft[field].trim()
    if (value === current[field]) return
    const previous = current[field]
    try {
      adoptUser(await profileApi.update({ [field]: value }))
      // Undo rather than a confirm: renaming yourself is not a decision needing a gate, and
      // the toast is where the way back lives.
      toast(`Saved. ${previous ? `Was “${previous}”.` : ''}`)
    } catch (cause) {
      setDraft((current) => ({ ...current, [field]: previous }))
      setError(cause instanceof ApiError ? cause.message : 'That could not be saved.')
    }
  }

  return (
    <section className="panel-block">
      <h3 className="panel-block__title">Name</h3>
      {error ? <Banner tone="error">{error}</Banner> : null}
      <TextField
        label="First name"
        value={draft.first_name}
        onChange={(event) => setDraft({ ...draft, first_name: event.target.value })}
        onBlur={() => void saveField('first_name')}
        hint="Your badge shows the first letter of this and of your last name."
      />
      <TextField
        label="Last name"
        value={draft.last_name}
        onChange={(event) => setDraft({ ...draft, last_name: event.target.value })}
        onBlur={() => void saveField('last_name')}
      />
      <TextField
        label="Display name"
        value={draft.display_name}
        onChange={(event) => setDraft({ ...draft, display_name: event.target.value })}
        onBlur={() => void saveField('display_name')}
        hint="What everyone sees. Change it freely — it does not affect your initials."
      />
    </section>
  )
}

function MyLocationBlock({ family }: { family: FamilyDetail | null }) {
  const { user } = useSession()
  const me = family?.members.find((m) => m.user_id === user?.id)
  const head = family?.members.find((m) => m.role === 'head')

  // Why they might not be visible, in the order the server evaluates it.
  const blockedBy =
    family && !family.location_sharing_allowed
      ? 'your family is currently hidden from the map'
      : me && !me.location_sharing_allowed
        ? 'your family has turned your marker off'
        : null

  return (
    <section className="panel-block">
      <h3 className="panel-block__title">My location</h3>
      <p className="panel-block__body">
        Sharing your live location is yours to decide, and nobody else can turn it on for you.
        The control itself arrives with the holiday stage, along with your browser&apos;s own
        permission prompt.
      </p>
      {blockedBy ? (
        <p className="panel-block__body muted">
          Note: {blockedBy}. Your own setting still works and is remembered — ask
          {head ? ` ${head.display_name}` : ' your head of family'} if you expected to be
          visible.
        </p>
      ) : null}
    </section>
  )
}

export function ProfileScreen() {
  const { user } = useSession()
  const [family, setFamily] = useState<FamilyDetail | null>(null)

  useEffect(() => {
    if (!user?.family?.id) return
    familiesApi
      .read(user.family.id)
      .then(setFamily)
      .catch(() => setFamily(null))
  }, [user?.family?.id])

  if (!user) return <Spinner />

  return (
    <div className="families">
      <header className="families__head">
        <h1>Your profile</h1>
        <p className="families__sub">
          Yours to change at any time, in any stage — including after the trip has finished.
        </p>
      </header>

      <div className="profile-grid">
        <AvatarBlock />
        <NameBlock />
        <MyLocationBlock family={family} />

        <section className="panel-block">
          <h3 className="panel-block__title">Account</h3>
          <dl className="profile-facts">
            <dt>Username</dt>
            <dd className="tabular">@{user.username}</dd>
            <dt>Family</dt>
            <dd>{user.family?.name ?? 'Not on a family yet'}</dd>
            <dt>Role</dt>
            <dd>
              {user.family ? ROLE_LABEL[user.family.role] : '—'}
              {user.is_owner ? ' · trip owner' : user.is_organiser ? ' · organiser' : ''}
            </dd>
          </dl>
          <p className="panel-block__body muted">
            Your username cannot be changed. Your password and theme are in the shell&apos;s
            own controls.
          </p>
        </section>
      </div>
    </div>
  )
}
