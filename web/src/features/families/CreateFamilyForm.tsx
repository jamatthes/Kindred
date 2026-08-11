/**
 * An organiser creating a family for someone else (FM-1).
 *
 * The colour is not offered. It is assigned automatically to the lowest free slot, and the
 * organiser can change it afterwards from the panel — asking someone to pick from eight
 * abstract slots before the family has a single member is a decision without information.
 * `409 no_color_slots` and `409 name_taken` come back on the name field, where the person can
 * act on them.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { useToast } from '../../app/ui/toastContext'
import type { FamilyDetail } from '../../app/types'
import { familiesApi } from './api'

export function CreateFamilyForm({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (family: FamilyDetail) => void
}) {
  const toast = useToast()
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [busy, setBusy] = useState(false)
  const [nameError, setNameError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) {
      setNameError('A family name is required.')
      return
    }
    setBusy(true)
    setNameError(null)
    setError(null)
    try {
      const family = await familiesApi.create({
        name: name.trim(),
        ...(address.trim() ? { home_address: address.trim() } : {}),
      })
      toast(`${family.name} added.`)
      onCreated(family)
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'name_taken') setNameError(cause.message)
      else if (cause instanceof ApiError) setError(cause.message)
      else setError('That family could not be created.')
      setBusy(false)
    }
  }

  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Create a family">
      <form className="modal-card" onSubmit={submit} noValidate>
        <h2>Create a family</h2>
        <p className="muted">
          They get their own colour on the map. You can invite their members afterwards.
        </p>

        {error ? <Banner tone="error">{error}</Banner> : null}

        <TextField
          label="Family name"
          autoFocus
          value={name}
          error={nameError}
          disabled={busy}
          onChange={(event) => setName(event.target.value)}
        />
        <TextField
          label="Home address"
          value={address}
          disabled={busy}
          hint="Optional — you or they can add it later."
          onChange={(event) => setAddress(event.target.value)}
        />

        <div className="panel-block__actions">
          <Button type="submit" busy={busy}>
            Create family
          </Button>
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  )
}
