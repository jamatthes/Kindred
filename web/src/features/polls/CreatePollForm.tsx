/**
 * Creating a poll (PL-1, PL-2).
 *
 * Coordinates are entered as numbers rather than picked on a map. `plan/architecture.md`
 * reserves the browser Maps SDK for the create-suggestion flow, and there is no configured
 * key in this environment — so the *data* side is complete and the picker arrives with the
 * map shell. An option without coordinates is perfectly valid: it is simply not on the map.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import type { Poll, PollKind } from '../../app/types'
import { pollsApi } from './api'

type Draft = { label: string; lat: string; lng: string }

const EMPTY: Draft = { label: '', lat: '', lng: '' }

export function CreatePollForm({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (poll: Poll) => void
}) {
  const toast = useToast()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [kind, setKind] = useState<PollKind>('score_matrix')
  const [allowMemberOptions, setAllowMemberOptions] = useState(false)
  const [options, setOptions] = useState<Draft[]>([{ ...EMPTY }, { ...EMPTY }])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function update(index: number, patch: Partial<Draft>) {
    setOptions((current) =>
      current.map((option, i) => (i === index ? { ...option, ...patch } : option)),
    )
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (!title.trim()) {
      setError('The poll needs a title.')
      return
    }
    const filled = options.filter((option) => option.label.trim())
    if (kind === 'options' && filled.length < 2) {
      setError('A single-choice poll needs at least two options to choose between.')
      return
    }

    setBusy(true)
    try {
      const created = await pollsApi.create({
        title: title.trim(),
        description: description.trim() || undefined,
        kind,
        allow_member_options: allowMemberOptions,
        options: filled.map((option) => ({
          label: option.label.trim(),
          // Both or neither — half a coordinate is refused by the server, and offering it
          // here would only turn that into a round trip.
          ...(option.lat.trim() && option.lng.trim()
            ? { lat: Number(option.lat), lng: Number(option.lng) }
            : {}),
        })),
      })
      toast(`“${created.title}” is open.`)
      onCreated(created)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That poll could not be created.')
      setBusy(false)
    }
  }

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Create a poll">
      <form className="modal-card modal-card--wide" onSubmit={submit} noValidate>
        <h2>Create a poll</h2>

        {error ? <Banner tone="error">{error}</Banner> : null}

        <TextField
          label="Question"
          autoFocus
          placeholder="Where shall we go?"
          value={title}
          disabled={busy}
          onChange={(event) => setTitle(event.target.value)}
        />
        <TextField
          label="Description"
          hint="Optional — a line explaining how to answer."
          value={description}
          disabled={busy}
          onChange={(event) => setDescription(event.target.value)}
        />

        <fieldset className="kind-choice">
          <legend>How do people answer?</legend>
          {(
            [
              ['score_matrix', 'Score every option', 'Everyone rates each option 1–10.'],
              ['options', 'Pick one', 'Each person chooses a single option.'],
            ] as const
          ).map(([value, label, hint]) => (
            <label key={value} className={kind === value ? 'is-on' : undefined}>
              <input
                type="radio"
                name="kind"
                checked={kind === value}
                onChange={() => setKind(value)}
              />
              <span>
                <strong>{label}</strong>
                <span className="muted">{hint}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <label className="k-switch">
          <input
            type="checkbox"
            checked={allowMemberOptions}
            onChange={(event) => setAllowMemberOptions(event.target.checked)}
          />
          <span className="k-switch__track" aria-hidden="true">
            <span className="k-switch__thumb" />
          </span>
          <span className="k-switch__text">
            <span className="k-switch__label">Let anyone add options</span>
            <span className="k-switch__hint">
              Members can add their own suggestions while the poll is open.
            </span>
          </span>
        </label>

        <div className="option-drafts">
          <span className="panel-block__title">Options</span>
          {options.map((option, index) => (
            <div key={index} className="option-draft">
              <TextField
                label={`Option ${index + 1}`}
                value={option.label}
                disabled={busy}
                onChange={(event) => update(index, { label: event.target.value })}
              />
              <TextField
                label="Latitude"
                hint="Optional"
                value={option.lat}
                disabled={busy}
                onChange={(event) => update(index, { lat: event.target.value })}
              />
              <TextField
                label="Longitude"
                hint="Optional"
                value={option.lng}
                disabled={busy}
                onChange={(event) => update(index, { lng: event.target.value })}
              />
            </div>
          ))}
          <Button
            type="button"
            variant="ghost"
            onClick={() => setOptions((current) => [...current, { ...EMPTY }])}
          >
            Add another option
          </Button>
        </div>

        <div className="panel-block__actions">
          <Button type="submit" busy={busy}>
            Create poll
          </Button>
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  )
}
