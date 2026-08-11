/**
 * The trip's four fields — name, dates, timezone.
 *
 * **One component, two frames.** Section 1 of the console renders it inside the app shell;
 * the AC-0 setup screen renders it on a card of its own before the shell exists. Two
 * implementations would be two places for the same validation to drift, and the validation
 * is the part that matters: the name is required, the dates are legitimately unknown during
 * Planning, and the end date may not precede the start.
 *
 * Both frames write through `PATCH /admin/trip`. There is no separate "create" endpoint,
 * because there is no separate creation — the trip exists from the seed and setup is the
 * first edit of it.
 */

import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import type { TripAdmin } from '../../app/types'
import { adminApi } from './api'
import type { TripPatch } from './api'
import './admin.css'

/** The browser's own IANA list where it has one — no bundled copy to go stale. */
function timezoneOptions(): string[] {
  const supported = (
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf
  try {
    const zones = supported?.('timeZone')
    if (zones && zones.length > 0) return zones
  } catch {
    /* fall through */
  }
  return [Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', 'UTC']
}

export type TripFormProps = {
  trip: TripAdmin
  /** "Save" in the console, "Create trip" on the setup screen. */
  submitLabel: string
  onSaved: (trip: TripAdmin) => void
  /** The setup screen wants the dates explained as optional; the console does not. */
  datesOptionalHint?: boolean
}

export function TripForm({ trip, submitLabel, onSaved, datesOptionalHint }: TripFormProps) {
  const [name, setName] = useState(trip.name)
  const [startDate, setStartDate] = useState(trip.start_date ?? '')
  const [endDate, setEndDate] = useState(trip.end_date ?? '')
  const [timezone, setTimezone] = useState(trip.timezone)

  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const zones = useMemo(timezoneOptions, [])

  const dirty =
    name !== trip.name ||
    startDate !== (trip.start_date ?? '') ||
    endDate !== (trip.end_date ?? '') ||
    timezone !== trip.timezone

  function validate(): boolean {
    const next: Record<string, string> = {}
    if (!name.trim()) next.name = 'The trip needs a name.'
    if (!timezone.trim()) next.timezone = 'Choose a timezone.'
    if (startDate && endDate && endDate < startDate) {
      next.end_date = 'The end date cannot be before the start date.'
    }
    setFieldErrors(next)
    return Object.keys(next).length === 0
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (!validate()) return

    // Only what changed. A PATCH that sends every field would overwrite a value another
    // organiser edited while this form was open.
    const patch: TripPatch = {}
    if (name !== trip.name) patch.name = name.trim()
    if (startDate !== (trip.start_date ?? '')) patch.start_date = startDate || null
    if (endDate !== (trip.end_date ?? '')) patch.end_date = endDate || null
    if (timezone !== trip.timezone) patch.timezone = timezone

    setBusy(true)
    try {
      onSaved(await adminApi.patchTrip(patch))
      setFieldErrors({})
    } catch (cause) {
      if (cause instanceof ApiError) {
        // The server blames a field where it can; put the message there rather than in a
        // banner the reader has to map back onto an input.
        const perField: Record<string, string> = {}
        for (const item of cause.errors) perField[item.field.split('.').pop() ?? ''] = item.message
        if (Object.keys(perField).length > 0) setFieldErrors(perField)
        else setError(cause.message)
      } else {
        setError('Something went wrong. Try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="trip-form" onSubmit={onSubmit} noValidate>
      {error ? <Banner tone="error">{error}</Banner> : null}

      <TextField
        label="Trip name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        error={fieldErrors.name}
        disabled={busy}
        autoComplete="off"
      />

      <div className="trip-form__dates">
        <TextField
          label="Start date"
          type="date"
          value={startDate}
          onChange={(event) => setStartDate(event.target.value)}
          error={fieldErrors.start_date}
          disabled={busy}
          hint={datesOptionalHint ? 'You can decide this later.' : undefined}
        />
        <TextField
          label="End date"
          type="date"
          value={endDate}
          onChange={(event) => setEndDate(event.target.value)}
          error={fieldErrors.end_date}
          disabled={busy}
          hint={datesOptionalHint ? 'You can decide this later.' : undefined}
        />
      </div>
      {!startDate && !endDate && !datesOptionalHint ? (
        // In Planning, no dates is the normal state — not an error, and not a blank either.
        <p className="trip-form__placeholder">Dates not decided yet.</p>
      ) : null}

      <label className="k-field" htmlFor="trip-timezone">
        <span className="k-field__label">Timezone</span>
        <input
          id="trip-timezone"
          className="k-field__input"
          list="trip-timezone-options"
          value={timezone}
          onChange={(event) => setTimezone(event.target.value)}
          disabled={busy}
          autoComplete="off"
        />
        <datalist id="trip-timezone-options">
          {zones.map((zone) => (
            <option value={zone} key={zone} />
          ))}
        </datalist>
        {fieldErrors.timezone ? (
          <span className="k-field__error" role="alert">
            {fieldErrors.timezone}
          </span>
        ) : (
          <span className="k-field__hint">
            All the trip's dates and times are read in this zone.
          </span>
        )}
      </label>

      <div className="trip-form__actions">
        {/* Explicit save, disabled until something changes: these are consequential values
            and AC-2 says they are not saved on blur. */}
        <Button type="submit" busy={busy} disabled={!dirty}>
          {submitLabel}
        </Button>
        {dirty ? <span className="admin__hint">Unsaved changes</span> : null}
      </div>
    </form>
  )
}
