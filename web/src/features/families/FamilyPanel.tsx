/**
 * The selected family's detail — the 38% side panel on desktop, a bottom sheet on a phone.
 *
 * `plan/design-system.md` is explicit that analytical content never goes in a modal: on a
 * phone it goes in a sheet the user can raise, which is why the same content is rendered into
 * `BottomSheet` below the tablet breakpoint rather than being reflowed into a dialog.
 *
 * What is *editable* here is decided from what the server sent back, not from a role
 * comparison assembled in the client: the address block is editable when the address is
 * present at all, and the member controls when the viewer's own membership says head or
 * spouse. The server refuses regardless — hiding a control is a courtesy, not a permission.
 */

import { useEffect, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { useSession } from '../../app/session'
import { BottomSheet } from '../../app/BottomSheet'
import { Banner, Button, Skeleton, TextField } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import { IdentityBadge } from '../../design/IdentityBadge'
import { PANEL_SHEET_QUERY } from '../../design/breakpoints'
import type { FamilyDetail, Member } from '../../app/types'
import { familiesApi } from './api'
import { useFamilyDetail } from './useFamilies'
import { HomeAddressBlock } from './HomeAddressBlock'
import { LocationSettingsBlock } from './LocationSettingsBlock'
import { InviteBlock } from './InviteBlock'
import { ROLE_LABEL } from './labels'


function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(
    () => window.matchMedia?.(PANEL_SHEET_QUERY).matches ?? false,
  )
  useEffect(() => {
    const query = window.matchMedia?.(PANEL_SHEET_QUERY)
    if (!query) return
    const update = () => setNarrow(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return narrow
}

function MemberRow({
  family,
  member,
  editable,
  viewerIsSpouse,
  onChanged,
}: {
  family: FamilyDetail
  member: Member
  editable: boolean
  viewerIsSpouse: boolean
  onChanged: (next: FamilyDetail) => void
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The spouse asymmetry (FM-16), and the head-always-exists rule. Both are enforced by the
  // server; rendering them here stops a control being offered that would only ever fail.
  const targetIsHead = member.role === 'head'
  const protectedTarget = (viewerIsSpouse && targetIsHead) || member.is_owner
  const canChangeRole = editable && !viewerIsSpouse && !member.is_owner
  const canRemove = editable && !targetIsHead && !protectedTarget

  async function setRole(role: Member['role']) {
    setBusy(true)
    setError(null)
    try {
      await familiesApi.updateMember(family.id, member.user_id, { role })
      onChanged(await familiesApi.read(family.id))
      toast(role === 'head' ? 'Head of family changed.' : 'Role updated.')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That could not be changed.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await familiesApi.removeMember(family.id, member.user_id)
      onChanged(await familiesApi.read(family.id))
      toast(`${member.display_name} removed from ${family.name}.`)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That person could not be removed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="member-row">
      <IdentityBadge
        initials={member.initials}
        familyColor={family.color}
        avatarThumbUrl={member.avatar_thumb_url}
        size={32}
        name={member.display_name}
      />
      <span className="member-row__who">
        <span className="member-row__name">{member.display_name}</span>
        <span className="member-row__meta">
          @{member.username} · {ROLE_LABEL[member.role]}
          {member.is_owner ? ' · trip owner' : member.is_organiser ? ' · organiser' : ''}
        </span>
        {error ? <span className="member-row__error">{error}</span> : null}
      </span>

      {editable ? (
        <span className="member-row__actions">
          {canChangeRole && member.role === 'member' ? (
            <Button variant="ghost" onClick={() => void setRole('spouse')} disabled={busy}>
              Make spouse
            </Button>
          ) : null}
          {canChangeRole && member.role === 'spouse' ? (
            <>
              <Button variant="ghost" onClick={() => void setRole('member')} disabled={busy}>
                Make member
              </Button>
              <Button variant="ghost" onClick={() => void setRole('head')} disabled={busy}>
                Make head
              </Button>
            </>
          ) : null}
          {canRemove ? (
            <Button variant="ghost" onClick={() => void remove()} disabled={busy}>
              Remove
            </Button>
          ) : null}
        </span>
      ) : null}
    </li>
  )
}

function PanelBody({
  family,
  onChanged,
}: {
  family: FamilyDetail
  onChanged: (next: FamilyDetail) => void
}) {
  const { user } = useSession()
  const toast = useToast()
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(family.name)
  const [error, setError] = useState<string | null>(null)

  const mine = family.members.find((m) => m.user_id === user?.id)
  const viewerIsSpouse = mine?.role === 'spouse'
  const manages = Boolean(user?.is_organiser) || mine?.role === 'head' || viewerIsSpouse

  async function rename() {
    const previous = family.name
    const next = draft.trim()
    if (!next || next === previous) {
      setRenaming(false)
      return
    }
    // Optimistic, rolled back on failure (`design.md` > Loading).
    onChanged({ ...family, name: next })
    setRenaming(false)
    try {
      onChanged(await familiesApi.update(family.id, { name: next }))
      toast('Family renamed.')
    } catch (cause) {
      onChanged({ ...family, name: previous })
      setDraft(previous)
      setError(cause instanceof ApiError ? cause.message : 'That name could not be saved.')
    }
  }

  return (
    <div className="family-panel__body">
      {error ? <Banner tone="error">{error}</Banner> : null}

      <header className="family-panel__head">
        <span
          className="fcard__dot"
          style={{ background: `var(--family-${family.color})` }}
          aria-hidden="true"
        />
        {renaming ? (
          <TextField
            label="Family name"
            value={draft}
            autoFocus
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => void rename()}
          />
        ) : (
          <>
            <h2>{family.name}</h2>
            {manages ? (
              <Button variant="ghost" onClick={() => setRenaming(true)}>
                Rename
              </Button>
            ) : null}
          </>
        )}
      </header>

      <HomeAddressBlock family={family} editable={manages} onChanged={onChanged} />

      <section className="panel-block">
        <h3 className="panel-block__title">
          Members <span className="tabular">{family.member_count}</span>
        </h3>
        <ul className="member-list">
          {family.members.map((member) => (
            <MemberRow
              key={member.user_id}
              family={family}
              member={member}
              editable={manages}
              viewerIsSpouse={viewerIsSpouse}
              onChanged={onChanged}
            />
          ))}
        </ul>
        {family.member_count === 1 ? (
          <p className="panel-block__body muted">
            Just one person so far — invite the rest of the family below.
          </p>
        ) : null}
      </section>

      <LocationSettingsBlock
        family={family}
        editable={manages}
        viewerId={user?.id}
        onChanged={onChanged}
      />

      <InviteBlock familyId={family.id} editable={manages} />
    </div>
  )
}

export function FamilyPanel({
  familyId,
  onClose,
}: {
  familyId: string
  onClose: () => void
}) {
  const { family, loading, error, set } = useFamilyDetail(familyId)
  const narrow = useIsNarrow()

  const content = loading ? (
    <div className="family-panel__body" aria-busy="true">
      <Skeleton height="var(--text-sub)" width="60%" />
      <div style={{ height: 'var(--space-3)' }} />
      <Skeleton height="var(--space-5)" />
      <div style={{ height: 'var(--space-3)' }} />
      <Skeleton height="var(--space-6)" />
    </div>
  ) : error || !family ? (
    <div className="family-panel__body">
      <Banner tone="error">{error ?? 'That family could not be loaded.'}</Banner>
    </div>
  ) : (
    <PanelBody family={family} onChanged={set} />
  )

  if (narrow) {
    return (
      <BottomSheet open title={family?.name ?? 'Family'} onClose={onClose} initialSnap="full">
        {content}
      </BottomSheet>
    )
  }

  return (
    <aside className="family-panel" aria-label={family?.name ?? 'Family'}>
      <div className="family-panel__bar">
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
      {content}
    </aside>
  )
}
