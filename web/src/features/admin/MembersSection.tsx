/**
 * Section 4 — families and members.
 *
 * Two tables, one search box, the shared table pattern. Both row actions are
 * admin-destructive and get real confirms; both are disabled on the owner's row with a
 * tooltip saying why, because the owner is not a target of either at any permission level.
 *
 * Family *editing* is not here. The console links into the `families` panel rather than
 * duplicating its UI — one editor, one set of rules.
 */

import { useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { useNavigate } from '../../app/router'
import { useSession } from '../../app/session'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import { DataTable } from '../../app/ui/DataTable'
import type { Column } from '../../app/ui/DataTable'
import { useToast } from '../../app/ui/toastContext'
import type { AdminMember, Family } from '../../app/types'
import { adminApi } from './api'

function roleLabels(member: AdminMember): string[] {
  // Every label that applies, because the two kinds of role are independent: an organiser
  // who heads their family is both, and showing one would misdescribe them.
  const labels: string[] = []
  if (member.is_owner) labels.push('Owner')
  else if (member.is_organiser) labels.push('Organiser')
  if (member.family_role === 'head') labels.push('Head')
  if (member.family_role === 'spouse') labels.push('Spouse')
  if (labels.length === 0) labels.push('Member')
  return labels
}

export type MembersSectionProps = {
  families: Family[]
  members: AdminMember[]
  query: string
  onQueryChange: (value: string) => void
  onChanged: () => void
}

export function MembersSection({
  families,
  members,
  query,
  onQueryChange,
  onChanged,
}: MembersSectionProps) {
  const { user } = useSession()
  const navigate = useNavigate()
  const toast = useToast()

  const [resetting, setResetting] = useState<AdminMember | null>(null)
  const [removing, setRemoving] = useState<AdminMember | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** Shown once, then gone — the same copy-once pattern as an invite link. */
  const [temporary, setTemporary] = useState<{ name: string; password: string } | null>(null)

  async function doReset() {
    if (resetting === null) return
    setBusy(true)
    setError(null)
    try {
      const result = await adminApi.resetPassword(resetting.user_id)
      setTemporary({ name: resetting.display_name, password: result.temporary_password })
      setResetting(null)
      onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The reset did not happen.')
      setResetting(null)
    } finally {
      setBusy(false)
    }
  }

  async function doRemove() {
    if (removing === null) return
    setBusy(true)
    setError(null)
    try {
      await adminApi.removeUser(removing.user_id)
      setRemoving(null)
      onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'They were not removed.')
      setRemoving(null)
    } finally {
      setBusy(false)
    }
  }

  const memberColumns: Column<AdminMember>[] = [
    {
      key: 'name',
      header: 'Name',
      sortBy: (row) => row.display_name,
      render: (row) => (
        <span className="admin__person">
          <strong>{row.display_name}</strong>
          <span className="admin__muted">@{row.username}</span>
        </span>
      ),
    },
    {
      key: 'family',
      header: 'Family',
      sortBy: (row) => row.family?.name ?? null,
      render: (row) =>
        row.family ? (
          <span className="admin__family">
            <span
              className="admin__swatch"
              style={{ background: `var(--family-${row.family.color})` }}
              aria-hidden="true"
            />
            {row.family.name}
          </span>
        ) : (
          <span className="admin__muted">No family</span>
        ),
    },
    {
      key: 'role',
      header: 'Role',
      sortBy: (row) => roleLabels(row).join(' · '),
      render: (row) => roleLabels(row).join(' · '),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <span className="admin__chips">
          {row.must_change_password ? (
            <span className="admin__status-chip">⚠ Must change password</span>
          ) : null}
          {row.last_login_at === null ? (
            <span className="admin__status-chip">◌ Never logged in</span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'last_login',
      header: 'Last login',
      numeric: true,
      sortBy: (row) => row.last_login_at,
      render: (row) =>
        row.last_login_at ? (
          new Date(row.last_login_at).toLocaleDateString()
        ) : (
          <span className="admin__muted">never</span>
        ),
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (row) => {
        const isSelf = row.user_id === user?.id
        // Disabled rather than hidden, with the reason in the tooltip: a control that
        // vanishes for reasons the reader cannot see is harder to trust than one that
        // explains itself.
        const why = row.is_owner
          ? "The trip's owner cannot be reset or removed here."
          : isSelf
            ? 'Use your profile page for your own account.'
            : undefined
        return (
          <span className="admin__row-actions">
            <button
              type="button"
              className="admin__link"
              disabled={Boolean(why)}
              title={why}
              onClick={() => setResetting(row)}
            >
              Reset password
            </button>
            <button
              type="button"
              className="admin__link admin__link--danger"
              disabled={Boolean(why)}
              title={why}
              onClick={() => setRemoving(row)}
            >
              Remove
            </button>
          </span>
        )
      },
    },
  ]

  const familyColumns: Column<Family>[] = [
    {
      key: 'name',
      header: 'Family',
      sortBy: (row) => row.name,
      render: (row) => (
        <span className="admin__family">
          <span
            className="admin__swatch"
            style={{ background: `var(--family-${row.color})` }}
            aria-hidden="true"
          />
          <strong>{row.name}</strong>
        </span>
      ),
    },
    {
      key: 'members',
      header: 'Members',
      numeric: true,
      sortBy: (row) => row.member_count,
      render: (row) => row.member_count,
    },
    {
      key: 'home',
      header: 'Home',
      sortBy: (row) => row.home_locality ?? null,
      render: (row) =>
        row.home_placed ? (
          (row.home_locality ?? 'Placed')
        ) : (
          <span className="admin__muted">Not set</span>
        ),
    },
  ]

  return (
    <section className="admin__section" id="section-members" aria-labelledby="members-heading">
      <h2 className="admin__section-title" id="members-heading">
        Families and members
      </h2>

      {error ? <Banner tone="error">{error}</Banner> : null}

      {temporary !== null ? (
        // A copy-once block, not a dialog: it is a value to be read and passed on, and the
        // same pattern as an invite link. It disappears when dismissed and cannot be
        // retrieved — the server never had the plaintext after the response.
        <div className="admin__copy-once" role="status">
          <div>
            <strong>Temporary password for {temporary.name}</strong>
            <code>{temporary.password}</code>
            <span className="admin__hint">Shown only now. It cannot be retrieved later.</span>
          </div>
          <span className="admin__row-actions">
            <Button
              variant="secondary"
              onClick={() => {
                void navigator.clipboard?.writeText(temporary.password)
                toast('Copied')
              }}
            >
              Copy
            </Button>
            <Button variant="ghost" onClick={() => setTemporary(null)}>
              Done
            </Button>
          </span>
        </div>
      ) : null}

      <div className="admin__search">
        <TextField
          label="Search"
          placeholder="Name, username or family"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
      </div>

      <DataTable
        caption={`Members (${members.length})`}
        columns={memberColumns}
        rows={members}
        rowKey={(row) => row.user_id}
        empty="Nobody matches that search."
      />

      <div className="admin__spacer" />

      <DataTable
        caption={`Families (${families.length})`}
        columns={familyColumns}
        rows={families}
        rowKey={(row) => row.id}
        onRowClick={(row) => navigate({ name: 'families', familyId: row.id })}
        empty="No families match that search."
      />
      <p className="admin__hint">
        Editing a family — its home address, its members' roles, its invites — happens in the
        families view. This console links to it rather than keeping a second copy.
      </p>

      <ConfirmDialog
        open={resetting !== null}
        title={`Reset ${resetting?.display_name}'s password?`}
        consequences={[
          'They are signed out everywhere immediately.',
          'You get a temporary password to pass on, shown once.',
          'They must choose a new password on their next login.',
        ]}
        confirmLabel="Reset the password"
        busy={busy}
        onConfirm={() => void doReset()}
        onCancel={() => setResetting(null)}
      />

      <ConfirmDialog
        open={removing !== null}
        title={`Remove ${removing?.display_name} from the trip?`}
        body="Their account is kept, and so is everything they wrote."
        consequences={[
          'They lose access immediately and are signed out.',
          'Their votes, comments and suggestions stay, still attributed to them.',
          'You can invite them back; they would start with a fresh membership.',
        ]}
        confirmLabel="Remove from trip"
        tone="danger"
        busy={busy}
        onConfirm={() => void doRemove()}
        onCancel={() => setRemoving(null)}
      />

    </section>
  )
}
