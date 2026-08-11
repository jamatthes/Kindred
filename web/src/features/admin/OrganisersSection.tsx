/**
 * Section 8 — organisers (AC-13). **Owner only.**
 *
 * An organiser's console omits this section rather than showing it disabled: there is
 * nothing here for them that not seeing the card fails to convey, and a disabled card
 * invites the question of what it would do.
 *
 * The demote confirm deliberately does *not* borrow the language of Section 4's actions.
 * Removing someone from the trip revokes their access; demoting an organiser does not touch
 * their session or their family role, and saying so is the difference between a colleague
 * losing a permission and a colleague being thrown out.
 */

import { useMemo, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import type { AdminMember, Organiser } from '../../app/types'
import { adminApi } from './api'

export type OrganisersSectionProps = {
  organisers: Organiser[]
  /** The universe to appoint from — the same members Section 4 lists. */
  members: AdminMember[]
  onChanged: () => void
}

export function OrganisersSection({
  organisers,
  members,
  onChanged,
}: OrganisersSectionProps) {
  const [query, setQuery] = useState('')
  const [demoting, setDemoting] = useState<Organiser | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const candidates = useMemo(() => {
    const held = new Set(organisers.map((row) => row.user_id))
    const needle = query.trim().toLowerCase()
    return members
      .filter((row) => !row.is_owner && !held.has(row.user_id))
      .filter(
        (row) =>
          needle.length > 0 &&
          (row.display_name.toLowerCase().includes(needle) ||
            row.username.toLowerCase().includes(needle) ||
            (row.family?.name ?? '').toLowerCase().includes(needle)),
      )
      .slice(0, 6)
  }, [members, organisers, query])

  async function appoint(member: AdminMember) {
    setBusy(true)
    setError(null)
    try {
      await adminApi.appointOrganiser(member.user_id)
      setQuery('')
      onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'They were not appointed.')
    } finally {
      setBusy(false)
    }
  }

  async function demote() {
    if (demoting === null) return
    setBusy(true)
    setError(null)
    try {
      await adminApi.demoteOrganiser(demoting.user_id)
      setDemoting(null)
      onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'They were not removed.')
      setDemoting(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="admin__section"
      id="section-organisers"
      aria-labelledby="organisers-heading"
    >
      <h2 className="admin__section-title" id="organisers-heading">
        Organisers
      </h2>
      <p className="admin__hint">
        Organisers can do everything you can across every family — except this. Appointing and
        removing organisers is yours alone.
      </p>

      {error ? <Banner tone="error">{error}</Banner> : null}

      {organisers.length === 0 ? (
        <p className="admin__empty">
          No organisers yet — you're doing this alone, or you haven't needed help.
        </p>
      ) : (
        <ul className="organisers">
          {organisers.map((row) => (
            <li className="organisers__row" key={row.user_id}>
              <span
                className="admin__swatch admin__swatch--lg"
                style={{
                  background: row.family
                    ? `var(--family-${row.family.color})`
                    : 'var(--color-text-faint)',
                }}
                aria-hidden="true"
              >
                {row.initials}
              </span>
              <span className="organisers__who">
                <strong>{row.display_name}</strong>
                <span className="admin__muted">
                  {row.family ? row.family.name : 'No family'}
                  {row.family_role && row.family_role !== 'member'
                    ? ` · ${row.family_role === 'head' ? 'Head' : 'Spouse'}`
                    : ''}
                </span>
              </span>
              <span className="admin__muted organisers__meta">
                Appointed by {row.granted_by?.display_name ?? 'someone who has since left'} ·{' '}
                {new Date(row.created_at).toLocaleDateString()}
              </span>
              <button
                type="button"
                className="admin__link admin__link--danger"
                onClick={() => setDemoting(row)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="organisers__add">
        <TextField
          label="Add an organiser"
          placeholder="Search members by name, username or family"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          disabled={busy}
        />
        {candidates.length > 0 ? (
          <ul className="organisers__candidates">
            {candidates.map((member) => (
              <li key={member.user_id}>
                <span>
                  <strong>{member.display_name}</strong>{' '}
                  <span className="admin__muted">
                    @{member.username} · {member.family?.name ?? 'No family'}
                  </span>
                </span>
                <Button variant="secondary" busy={busy} onClick={() => void appoint(member)}>
                  Make organiser
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
        {query.trim() && candidates.length === 0 ? (
          <p className="admin__hint">Nobody left to appoint by that name.</p>
        ) : null}
      </div>

      <ConfirmDialog
        open={demoting !== null}
        title={`Remove ${demoting?.display_name} as an organiser?`}
        consequences={[
          'They lose every organiser power immediately.',
          'They keep their family role and everything it grants inside their own family.',
          'They stay signed in — this is a permission change, not a lock-out.',
        ]}
        confirmLabel="Remove organiser"
        busy={busy}
        onConfirm={() => void demote()}
        onCancel={() => setDemoting(null)}
      />
    </section>
  )
}
