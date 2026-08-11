/**
 * The family's location settings (FM-15).
 *
 * **Visible to every member of the family, editable only by its head or spouse and by the
 * owner and organisers.** Members see it read-only, and that is the whole point of the block:
 * a setting that silently overrides you, invisibly, is the thing this exists to prevent. If
 * someone's own toggle is having no effect, this is where they find out why and who to ask.
 *
 * Every control here can only ever *remove* a marker. There is no switch on this screen —
 * and no request body behind one — that turns another person's sharing on.
 */

import { useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import { IdentityBadge } from '../../design/IdentityBadge'
import type { FamilyDetail, Member } from '../../app/types'
import { familiesApi } from './api'
import { effectiveLocationState } from './labels'

function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  hint?: string
  disabled?: boolean
}) {
  return (
    <label className={`k-switch${disabled ? ' is-disabled' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="k-switch__track" aria-hidden="true">
        <span className="k-switch__thumb" />
      </span>
      <span className="k-switch__text">
        <span className="k-switch__label">{label}</span>
        {hint ? <span className="k-switch__hint">{hint}</span> : null}
      </span>
    </label>
  )
}

export function LocationSettingsBlock({
  family,
  editable,
  viewerId,
  onChanged,
}: {
  family: FamilyDetail
  editable: boolean
  viewerId: string | undefined
  onChanged: (next: FamilyDetail) => void
}) {
  const toast = useToast()
  const [error, setError] = useState<string | null>(null)
  const head = family.members.find((m) => m.role === 'head')
  const viewerIsSpouse =
    family.members.find((m) => m.user_id === viewerId)?.role === 'spouse'

  async function setPolicy(body: { sharing_allowed?: boolean; member_default?: boolean }) {
    const previous = family
    // Optimistic, with an explicit rollback: a switch that lags is a switch people press
    // twice.
    onChanged({
      ...family,
      location_sharing_allowed: body.sharing_allowed ?? family.location_sharing_allowed,
      member_location_default: body.member_default ?? family.member_location_default,
    })
    try {
      onChanged(await familiesApi.setLocationPolicy(family.id, body))
      if (body.sharing_allowed === false) {
        // Instantly reversible and it restores exactly the previous set of sharers, so an
        // undo toast rather than a confirm dialog — a confirm would be friction with no
        // decision behind it.
        toast('Your family is hidden from the map.')
      }
    } catch (cause) {
      onChanged(previous)
      setError(cause instanceof ApiError ? cause.message : 'That could not be saved.')
    }
  }

  async function setMemberSwitch(member: Member, allowed: boolean) {
    const previous = family
    onChanged({
      ...family,
      members: family.members.map((m) =>
        m.user_id === member.user_id ? { ...m, location_sharing_allowed: allowed } : m,
      ),
    })
    try {
      const updated = await familiesApi.updateMember(family.id, member.user_id, {
        location_sharing_allowed: allowed,
      })
      onChanged({
        ...family,
        members: family.members.map((m) => (m.user_id === updated.user_id ? updated : m)),
      })
    } catch (cause) {
      onChanged(previous)
      setError(cause instanceof ApiError ? cause.message : 'That could not be saved.')
    }
  }

  return (
    <section className="panel-block">
      <h3 className="panel-block__title">On the map</h3>

      {!editable ? (
        <p className="panel-block__body muted">
          Your family&apos;s head can change these. You are shown them so you can see whether
          your own sharing setting is currently having any effect.
        </p>
      ) : null}

      {error ? <Banner tone="error">{error}</Banner> : null}

      <Switch
        checked={family.location_sharing_allowed}
        disabled={!editable}
        onChange={(next) => void setPolicy({ sharing_allowed: next })}
        label="Show our family on the map"
        hint="When this is off, nobody in this family appears on the trip map, including you. It does not change anyone's own sharing setting — turning it back on restores whoever had chosen to share."
      />

      <Switch
        checked={family.member_location_default}
        disabled={!editable}
        onChange={(next) => void setPolicy({ member_default: next })}
        label="New members start with sharing on"
        hint="This only sets what the toggle starts at for someone joining later. It does not change anyone already in the family, and everyone is still asked by their browser before any location is sent."
      />

      <ul className="member-switches">
        {family.members.map((member) => {
          // The spouse asymmetry, rendered: a spouse may not switch the head off. The server
          // refuses regardless — this stops the control being offered and then failing.
          const targetIsHead = member.user_id === head?.user_id
          const blocked = viewerIsSpouse && targetIsHead
          return (
            <li key={member.user_id} className="member-switches__row">
              <IdentityBadge
                initials={member.initials}
                familyColor={family.color}
                avatarThumbUrl={member.avatar_thumb_url}
                size={32}
                name={member.display_name}
              />
              <span className="member-switches__who">
                <span className="member-switches__name">{member.display_name}</span>
                {/* The only place the three inputs are visible together to a person. */}
                <span className="member-switches__state">
                  {effectiveLocationState(member, family.location_sharing_allowed)}
                </span>
              </span>
              <Switch
                checked={member.location_sharing_allowed}
                disabled={!editable || blocked}
                onChange={(next) => void setMemberSwitch(member, next)}
                label={`Show ${member.display_name} on the map`}
              />
            </li>
          )
        })}
      </ul>
    </section>
  )
}
