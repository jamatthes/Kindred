/**
 * Progressive-disclosure level 3 — "Details" (`design.md`): the full record, in the side
 * panel (desktop) or bottom sheet (mobile). `MapSuggestionsScreen` decides which chrome
 * wraps this; the content is the same either way.
 *
 * The photo strip follows the tiering in `design.md` exactly, and the ToS invariant with
 * it: tier 1 (live Place Details) is fetched **in the browser only**, held in
 * `placesClient`'s short-TTL cache, and never touches `suggestionsApi`. Tier 2
 * (user-uploaded `attachments`) is explicitly out of scope for v1 per `requirements.md` —
 * "Photo upload onto suggestions ... handled by the archive work in a later milestone" — so
 * this panel skips straight from tier 1 to tier 3 (the link preview's `og:image`) and then
 * tier 4 (placeholder). Vote widgets and admin confirm/reject controls are only lightly
 * rendered here (a tally and a status control), per `PopoverCard`'s docblock: their full
 * design belongs to `voting-comments`, which is not part of this phase.
 */

import { useEffect, useState } from 'react'
import { Banner, Button } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import { useToast } from '../../app/ui/toastContext'
import { useSession } from '../../app/session'
import { useStage } from '../../app/useStage'
import { IdentityBadge } from '../../design/IdentityBadge'
import { familyColor } from '../../design/familyColor'
import { getPlaceDetails, placesAvailable } from './placesClient'
import { suggestionsApi } from './api'
import { suggestionStore } from './store'
import type { Suggestion, SuggestionStatus } from '../../app/types'
import './suggestionsList.css'
import './SuggestionDetailPanel.css'

const TYPE_LABEL: Record<Suggestion['type'], string> = {
  region: 'Region',
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
}

const STATUS_LABEL: Record<SuggestionStatus, string> = {
  proposed: 'Proposed',
  shortlisted: 'Shortlisted',
  approved: 'Approved',
  scheduled: 'Scheduled',
  rejected: 'Rejected',
}

/** `design.md` > "Status flow": every non-terminal move plus the rejection undo. */
const STATUS_ACTIONS: Partial<Record<SuggestionStatus, { to: SuggestionStatus; label: string }[]>> = {
  proposed: [
    { to: 'shortlisted', label: 'Shortlist' },
    { to: 'approved', label: 'Approve' },
    { to: 'rejected', label: 'Reject' },
  ],
  shortlisted: [
    { to: 'approved', label: 'Approve' },
    { to: 'rejected', label: 'Reject' },
    { to: 'proposed', label: 'Back to proposed' },
  ],
  approved: [
    { to: 'shortlisted', label: 'Back to shortlisted' },
    { to: 'rejected', label: 'Reject' },
  ],
  rejected: [{ to: 'proposed', label: 'Undo rejection' }],
}

function openInMapsUrl(s: Suggestion): string {
  if (s.type === 'region') return `https://www.google.com/maps/search/?api=1&query=${s.lat},${s.lng}`
  const dest = `https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lng}`
  return s.place_id ? `${dest}&destination_place_id=${s.place_id}` : dest
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function PhotoStrip({ suggestion }: { suggestion: Suggestion }) {
  const [photos, setPhotos] = useState<string[] | null>(null)
  const [linkImage, setLinkImage] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setPhotos(null)
    setLinkImage(null)
    setFailed(false)
    let cancelled = false

    if (suggestion.place_id && placesAvailable()) {
      getPlaceDetails(suggestion.place_id)
        .then((details) => {
          if (!cancelled) setPhotos(details.photoUrls)
        })
        .catch(() => {
          if (!cancelled) setFailed(true)
        })
      return () => {
        cancelled = true
      }
    }

    if (!suggestion.place_id && suggestion.external_url) {
      suggestionsApi
        .linkPreview(suggestion.external_url)
        .then((preview) => {
          if (!cancelled && preview?.image_url) setLinkImage(preview.image_url)
        })
        .catch(() => {
          // Best-effort; absent on failure, per design.md — no error chrome.
        })
      return () => {
        cancelled = true
      }
    }
    return () => {
      cancelled = true
    }
  }, [suggestion.id, suggestion.place_id, suggestion.external_url])

  if (suggestion.place_id && photos === null && !failed) {
    return (
      <div className="sugg-photos sugg-photos--loading" aria-busy="true">
        <div className="k-skeleton" style={{ height: 'var(--photo-strip-h)' }} />
      </div>
    )
  }

  const urls = photos && photos.length > 0 ? photos : linkImage ? [linkImage] : []
  if (urls.length === 0) return <div className="sugg-photos sugg-photos--placeholder" aria-hidden="true" />

  return (
    <div className="sugg-photos">
      {urls.map((url) => (
        <img key={url} src={url} alt="" loading="lazy" />
      ))}
    </div>
  )
}

export type SuggestionDetailPanelProps = {
  suggestion: Suggestion
  onChanged: (suggestion: Suggestion) => void
  onDeleted: (id: string) => void
  onBack?: () => void
}

export function SuggestionDetailPanel({ suggestion, onChanged, onDeleted, onBack }: SuggestionDetailPanelProps) {
  const { user } = useSession()
  const stage = useStage()
  const showToast = useToast()
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isAuthor = user?.id === suggestion.created_by.user_id
  const isFamilyLead =
    user?.family?.id === suggestion.created_by.family_id && (user.family.role === 'head' || user.family.role === 'spouse')
  const canEdit = Boolean(isAuthor || isFamilyLead || user?.is_owner || user?.is_organiser)
  const canChangeStatus = Boolean(user?.is_owner || user?.is_organiser)
  const canMutate = stage.canMutate

  async function changeStatus(to: SuggestionStatus) {
    setBusy(true)
    setError(null)
    try {
      onChanged(await suggestionsApi.setStatus(suggestion.id, to))
    } catch {
      setError('That status change could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  async function doDelete() {
    setBusy(true)
    setError(null)
    try {
      await suggestionsApi.remove(suggestion.id)
      onDeleted(suggestion.id)
      showToast('Suggestion deleted.')
    } catch {
      setError('That could not be deleted — it may already be scheduled into the itinerary.')
    } finally {
      setBusy(false)
      setConfirmingDelete(false)
    }
  }

  function handleDeleteClick() {
    const hasEngagement = (suggestion.vote_summary?.count ?? 0) > 0 || suggestion.comment_count > 0
    if (hasEngagement) setConfirmingDelete(true)
    else void doDelete()
  }

  return (
    <div className="sugg-detail">
      {onBack ? (
        <button type="button" className="sugg-detail__back" onClick={onBack}>
          ← Back to list
        </button>
      ) : null}

      <PhotoStrip suggestion={suggestion} />

      <header className="sugg-detail__head">
        <div>
          <h2>{suggestion.title}</h2>
          <p className="sugg-detail__meta">
            {TYPE_LABEL[suggestion.type]} · <span className={`sugg-status sugg-status--${suggestion.status}`}>{STATUS_LABEL[suggestion.status]}</span>
          </p>
        </div>
        <IdentityBadge
          initials={suggestion.created_by.display_name.slice(0, 2).toUpperCase()}
          familyColor={familyColor({ color: suggestion.created_by.family_color, color_custom: suggestion.created_by.family_color_custom ?? null })}
          size={32}
          name={suggestion.created_by.display_name}
        />
      </header>

      {suggestion.notes ? <p className="sugg-detail__notes">{suggestion.notes}</p> : null}

      {suggestion.place_snapshot ? (
        <p className="sugg-detail__address">{suggestion.place_snapshot.address}</p>
      ) : null}

      <div className="sugg-detail__row">
        <a className="sugg-detail__maps" href={openInMapsUrl(suggestion)} target="_blank" rel="noreferrer">
          Open in Google Maps
        </a>
        {suggestion.external_url ? (
          <a className="sugg-detail__link" href={suggestion.external_url} target="_blank" rel="noreferrer">
            View listing
          </a>
        ) : null}
      </div>

      {suggestion.vote_summary ? (
        <div className="sugg-detail__votes" aria-label="Votes">
          {suggestion.vote_summary.mode === 'score' ? (
            <span>
              {suggestion.vote_summary.average?.toFixed(1) ?? 'No scores yet'} · {suggestion.vote_summary.count} vote
              {suggestion.vote_summary.count === 1 ? '' : 's'}
            </span>
          ) : (
            <span>
              {suggestion.vote_summary.up ?? 0} for · {suggestion.vote_summary.down ?? 0} against
            </span>
          )}
        </div>
      ) : null}

      {suggestion.distances.length > 0 ? (
        <div className="sugg-detail__distances">
          <h3>Distance from each family</h3>
          <ul>
            {suggestion.distances.map((d) => (
              <li key={d.family_id}>
                <span>{d.family_name}</span>
                <span className="tabular">
                  {formatDuration(d.duration_s)}
                  {d.is_estimate ? ' (estimate)' : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {suggestion.children.length > 0 ? (
        <div className="sugg-detail__children">
          <h3>{suggestion.children.length} things here</h3>
          <ul>
            {suggestion.children.map((child) => (
              <li key={child.id}>
                <button type="button" onClick={() => suggestionStore.select(child.id)}>
                  {child.title} <span className="sugg-detail__child-type">{TYPE_LABEL[child.type]}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="sugg-detail__comments-slot">
        {suggestion.comment_count} comment{suggestion.comment_count === 1 ? '' : 's'} — the full thread arrives
        with `voting-comments`.
      </div>

      {error ? <Banner tone="error">{error}</Banner> : null}

      {canMutate && canChangeStatus && STATUS_ACTIONS[suggestion.status] ? (
        <div className="sugg-detail__status-actions" aria-label="Change status">
          {STATUS_ACTIONS[suggestion.status]!.map((action) => (
            <Button key={action.to} variant="secondary" busy={busy} onClick={() => void changeStatus(action.to)}>
              {action.label}
            </Button>
          ))}
        </div>
      ) : null}

      {canMutate && canEdit ? (
        <div className="sugg-detail__owner-actions">
          <Button variant="danger" busy={busy} onClick={handleDeleteClick}>
            Delete
          </Button>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmingDelete}
        title="Delete this suggestion?"
        body="It has votes or comments from the group."
        consequences={['Votes and comments on it are removed.', 'This cannot be undone.']}
        confirmLabel="Delete suggestion"
        tone="danger"
        busy={busy}
        onConfirm={() => void doDelete()}
        onCancel={() => setConfirmingDelete(false)}
      />
    </div>
  )
}
