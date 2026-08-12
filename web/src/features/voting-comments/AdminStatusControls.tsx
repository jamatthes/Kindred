/**
 * AdminStatusControls — V9: the status-transition block, visually separated at the bottom
 * of the side panel "so it reads as a different kind of authority" (`design.md`).
 *
 * `map-suggestions/design.md` owns the `status` *field*; this feature owns the
 * *transitions* and their UI, per this feature's own opening line — this component
 * replaces the inline status buttons `map-suggestions/SuggestionDetailPanel.tsx` shipped as
 * a placeholder ahead of this phase.
 *
 * Only buttons for transitions valid from the current status are rendered — absent, not
 * disabled-and-mysterious. Reject alone gets a real confirm dialog (admin-destructive,
 * `plan/design-system.md`); approve/shortlist/reopen commit directly because they are
 * reversible. A `409` (another admin already moved it) is not handled by retrying — the
 * caller's `suggestion` prop is driven by `useSuggestionList`'s own `suggestion.status_changed`
 * subscription one level up, so the correct status arrives and replaces this component's
 * transition options within a render; this component only needs to stop claiming the old
 * status is still current.
 */

import { useState } from 'react'
import { Banner, Button } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import { ApiError } from '../../app/apiClient'
import { suggestionsApi } from '../map-suggestions/api'
import type { Suggestion, SuggestionStatus } from '../../app/types'

const TRANSITIONS: Partial<Record<SuggestionStatus, { to: SuggestionStatus; label: string; destructive?: boolean }[]>> = {
  proposed: [
    { to: 'shortlisted', label: 'Shortlist' },
    { to: 'approved', label: 'Approve' },
    { to: 'rejected', label: 'Reject', destructive: true },
  ],
  shortlisted: [
    { to: 'approved', label: 'Approve' },
    { to: 'rejected', label: 'Reject', destructive: true },
    { to: 'proposed', label: 'Back to proposed' },
  ],
  approved: [
    { to: 'shortlisted', label: 'Back to shortlisted' },
    { to: 'rejected', label: 'Reject', destructive: true },
  ],
  rejected: [{ to: 'proposed', label: 'Reopen' }],
}

export type AdminStatusControlsProps = {
  suggestion: Suggestion
  canAdminister: boolean
  onChanged: (suggestion: Suggestion) => void
}

export function AdminStatusControls({ suggestion, canAdminister, onChanged }: AdminStatusControlsProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmReject, setConfirmReject] = useState(false)

  // The whole block does not render for non-admins — an absence, not a disabled control.
  if (!canAdminister) return null

  const options = TRANSITIONS[suggestion.status] ?? []
  if (options.length === 0) return null

  async function commit(to: SuggestionStatus) {
    setBusy(true)
    setError(null)
    try {
      onChanged(await suggestionsApi.setStatus(suggestion.id, to))
    } catch (cause) {
      // A racing admin: the current suggestion prop (fed by suggestion.status_changed one
      // level up) is already the honest answer, so this only needs to say why the click did
      // nothing rather than retry against a status that has moved on.
      setError(
        cause instanceof ApiError && cause.status === 409
          ? 'Someone else already changed this suggestion’s status.'
          : 'That status change could not be saved.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="admin-status" aria-label="Admin controls">
      <span className="admin-status__note">Organiser controls</span>
      {error ? <Banner tone="error">{error}</Banner> : null}
      <div className="admin-status__actions">
        {options.map((option) =>
          option.destructive ? (
            <Button key={option.to} variant="danger" disabled={busy} onClick={() => setConfirmReject(true)}>
              {option.label}
            </Button>
          ) : (
            <Button key={option.to} variant="secondary" disabled={busy} onClick={() => void commit(option.to)}>
              {option.label}
            </Button>
          ),
        )}
      </div>

      <ConfirmDialog
        open={confirmReject}
        title={`Reject "${suggestion.title}"?`}
        body="It will be hidden from the default suggestion list."
        consequences={['Votes and comments already on it are kept.', 'Any organiser can reopen it later.']}
        confirmLabel="Reject suggestion"
        tone="danger"
        busy={busy}
        onCancel={() => setConfirmReject(false)}
        onConfirm={() => {
          setConfirmReject(false)
          void commit('rejected')
        }}
      />
    </div>
  )
}
