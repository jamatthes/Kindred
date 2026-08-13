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
 * tier 4 (placeholder).
 *
 * The vote control, tally, comment thread, and admin status controls are `voting-comments`'
 * components (`SuggestionVotePanel`, `CommentThread`, `AdminStatusControls`) — this panel
 * used plain placeholders for all three ahead of that feature; this is the swap the NOTE at
 * the bottom of `plan/features/map-suggestions/design.md` described.
 *
 * The distance block is `distances`' `FamilyDistanceExpander` (own family first, then every
 * family on request) plus a single-suggestion force-recompute for organisers — the plain
 * duration list this panel shipped as a Phase-8 placeholder is the swap
 * `distances/design.md`'s own handoff NOTE described.
 */

import { useEffect, useState } from 'react'
import { Banner, Button } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import { useToast } from '../../app/ui/toastContext'
import { useSession } from '../../app/session'
import { useStage } from '../../app/useStage'
import { useNavigate } from '../../app/router'
import { IdentityBadge } from '../../design/IdentityBadge'
import { familyColor } from '../../design/familyColor'
import { getPlaceDetails, placesAvailable } from './placesClient'
import { suggestionsApi } from './api'
import { suggestionStore } from './store'
import { SuggestionVotePanel } from '../voting-comments/SuggestionVotePanel'
import { CommentThread } from '../voting-comments/CommentThread'
import { AdminStatusControls } from '../voting-comments/AdminStatusControls'
import { FamilyDistanceExpander } from '../distances/FamilyDistanceExpander'
import { RecomputeButton } from '../distances/RecomputeButton'
import { useRecompute } from '../distances/useRecompute'
import type { Suggestion, SuggestionStatus } from '../../app/types'
import './suggestionsList.css'
import './SuggestionDetailPanel.css'

const TYPE_LABEL: Record<Suggestion['type'], string> = {
  region: 'Region',
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
  other: 'Other',
}

const STATUS_LABEL: Record<SuggestionStatus, string> = {
  proposed: 'Proposed',
  shortlisted: 'Shortlisted',
  approved: 'Approved',
  scheduled: 'Scheduled',
  rejected: 'Rejected',
}

function openInMapsUrl(s: Suggestion): string {
  if (s.type === 'region') return `https://www.google.com/maps/search/?api=1&query=${s.lat},${s.lng}`
  const dest = `https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lng}`
  return s.place_id ? `${dest}&destination_place_id=${s.place_id}` : dest
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
  /** What the back button says. Defaults to the list, which is where it went when the list
   *  was always on screen — since the map-first redesign (`design.md` > "Layout") a detail
   *  opened from a pin dismisses to the bare map instead, and the caller that knows which
   *  says so. A button promising a list the user never opened is a small lie the panel
   *  should not be telling on the screen's behalf. */
  backLabel?: string
}

export function SuggestionDetailPanel({
  suggestion,
  onChanged,
  onDeleted,
  onBack,
  backLabel = '← Back to list',
}: SuggestionDetailPanelProps) {
  const { user } = useSession()
  const stage = useStage()
  const navigate = useNavigate()
  const showToast = useToast()
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // A failed distance chip's "Retry" is the same suggestion-scoped recompute the panel's
  // own button below triggers (the endpoint has no per-family granularity) — a second
  // instance so its own toast/busy state doesn't fight the button's.
  const chipRetry = useRecompute()

  // The place's own website, for the "Website" link below. A second `getPlaceDetails` call
  // for the same id inside the TTL is a cache hit in `placesClient`, so this costs no extra
  // request despite `PhotoStrip` asking for the same record — cheaper than threading state
  // between two siblings that each want one field of it.
  const [placeWebsite, setPlaceWebsite] = useState<string | null>(null)
  useEffect(() => {
    setPlaceWebsite(null)
    if (!suggestion.place_id || !placesAvailable()) return
    let cancelled = false
    getPlaceDetails(suggestion.place_id)
      .then((details) => {
        if (!cancelled) setPlaceWebsite(details.website)
      })
      .catch(() => {
        // Absent on failure — the link simply does not render (design.md: no error chrome
        // for a missing Places extra).
      })
    return () => {
      cancelled = true
    }
  }, [suggestion.place_id])

  const isAuthor = user?.id === suggestion.created_by.user_id
  const isFamilyLead =
    user?.family?.id === suggestion.created_by.family_id && (user.family.role === 'head' || user.family.role === 'spouse')
  const canEdit = Boolean(isAuthor || isFamilyLead || user?.is_owner || user?.is_organiser)
  const canAdminister = Boolean(user?.is_owner || user?.is_organiser)
  const canMutate = stage.canMutate

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
          {backLabel}
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
        {/* The place's own site, from the same live Place Details call that fetches the photo
            strip — never stored (ToS), fetched fresh on open. This is what makes it right for
            the create form to stop asking the user for a link on a Places-backed suggestion:
            the link is here without anyone typing it. */}
        {placeWebsite ? (
          <a className="sugg-detail__link" href={placeWebsite} target="_blank" rel="noreferrer">
            Website
          </a>
        ) : null}
      </div>

      <SuggestionVotePanel
        suggestionId={suggestion.id}
        suggestionType={suggestion.type}
        title={suggestion.title}
        density="full"
        canVote={Boolean(user) && canMutate}
      />

      {suggestion.distances.length > 0 ? (
        <div className="sugg-detail__distances">
          <h3>Distance from each family</h3>
          <FamilyDistanceExpander
            distances={suggestion.distances}
            ownFamilyId={user?.family?.id ?? null}
            suggestionType={suggestion.type}
            canRetryFailed={canAdminister}
            onRetryFamily={() => {
              if (!user?.trip) return
              void chipRetry.run(user.trip.id, suggestion.id).then((result) => {
                if (result) showToast(`Queued ${result.queued_pairs} pair${result.queued_pairs === 1 ? '' : 's'}.`)
              })
            }}
            onSetHomeFor={(familyId) => navigate({ name: 'families', familyId })}
          />
          {canAdminister && user?.trip ? (
            <RecomputeButton tripId={user.trip.id} suggestionId={suggestion.id} label="Force recompute this suggestion" />
          ) : null}
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

      <CommentThread subjectType="suggestion" subjectId={suggestion.id} />

      {error ? <Banner tone="error">{error}</Banner> : null}

      <AdminStatusControls suggestion={suggestion} canAdminister={canMutate && canAdminister} onChanged={onChanged} />

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
