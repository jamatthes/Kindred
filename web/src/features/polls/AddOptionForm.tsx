/**
 * AddOptionForm — the affordance PL-5 asked for and Phase 8 never listed
 * (`plan/features/polls/tasks.md`'s dated post-M2 note). `PollsScreen.tsx` decides *whether*
 * to render this (`canAddOption.ts`); this component only handles *how*.
 *
 * A label plus optional coordinates, reusing `CreatePollForm.tsx`'s own pattern exactly —
 * numeric lat/lng fields rather than a map picker, for the same reason that form gives:
 * there is no configured browser Maps key in this environment, and a located option without
 * one is still perfectly valid, just not on the map yet. The coordinate fields only appear
 * once the poll already has at least one located option ("if the poll is mappable",
 * `requirements.md` PL-5) — asking for a location on a table-only poll like "How long shall
 * we go for?" would be a field nobody has a reason to fill in.
 *
 * Closed on success rather than staying open for a second entry: `design.md`'s edge case
 * says the new option "inserts the column live" — the click that requested a refetch is a
 * discrete request-and-see-it-appear action, not a batch-entry mode (`CreatePollForm`, by
 * contrast, batches because it is filling in a whole poll at once).
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import type { Poll, PollOption } from '../../app/types'
import { pollsApi } from './api'

export function AddOptionForm({
  poll,
  onAdded,
}: {
  poll: Poll
  onAdded: (option: PollOption) => void
}) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [lat, setLat] = useState('')
  const [lng, setLng] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isMappable = poll.options.some((option) => option.lat !== null && option.lng !== null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!label.trim()) {
      setError('Give the option a label.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const created = await pollsApi.addOption(poll.id, {
        label: label.trim(),
        // Both or neither, same rule `CreatePollForm` uses — half a coordinate is refused
        // by the server.
        ...(lat.trim() && lng.trim() ? { lat: Number(lat), lng: Number(lng) } : {}),
      })
      onAdded(created)
      setLabel('')
      setLat('')
      setLng('')
      setOpen(false)
    } catch (cause) {
      // The 403 a member gets when `allow_member_options` was switched off after this form
      // opened, or the 409 when the trip has just frozen, both land here with the server's
      // own sentence — never a generic failure for a permission the person genuinely lacks.
      setError(cause instanceof ApiError ? cause.message : 'That option could not be added.')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <Button type="button" variant="ghost" onClick={() => setOpen(true)}>
        Add an option
      </Button>
    )
  }

  return (
    <form className="add-option" onSubmit={(event) => void submit(event)} noValidate>
      {error ? <Banner tone="error">{error}</Banner> : null}
      <TextField
        label="Option"
        autoFocus
        placeholder="Northumberland"
        value={label}
        disabled={busy}
        onChange={(event) => setLabel(event.target.value)}
      />
      {isMappable ? (
        <>
          <TextField
            label="Latitude"
            hint="Optional"
            value={lat}
            disabled={busy}
            onChange={(event) => setLat(event.target.value)}
          />
          <TextField
            label="Longitude"
            hint="Optional"
            value={lng}
            disabled={busy}
            onChange={(event) => setLng(event.target.value)}
          />
        </>
      ) : null}
      <div className="panel-block__actions">
        <Button type="submit" busy={busy}>
          Add option
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
