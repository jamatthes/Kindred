/**
 * The suggestion list, kept live by the WebSocket events in `design.md` > "WebSocket
 * events". Follows `polls/usePolls.ts`'s split: events that carry the whole changed record
 * (`suggestion.created`/`.updated`/`.moved`/`.status_changed`) are applied directly and
 * reconciled by `id` — "the echo of one's own event is idempotent" — so an optimistic edit
 * and its own server echo do not double-apply. Events owned by sibling features
 * (`suggestion.vote.updated`, `distance.updated`, comment counts) only ever touch fields
 * this feature does not compute itself, so those refetch the single affected record rather
 * than guessing at a partial merge.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { socket } from '../../app/socket'
import type { WsEnvelope } from '../../app/wsClient'
import type { DistanceStatus, Suggestion, SuggestionStatus } from '../../app/types'
import { suggestionsApi } from './api'
import type { SuggestionListParams } from './api'

export type SuggestionListState = {
  suggestions: Suggestion[]
  loading: boolean
  error: string | null
  reload: () => Promise<void>
  /** Applied optimistically by a mutation, then reconciled by the WS echo — never a second
   * source of truth, just the gap between "I clicked save" and "the server confirmed". */
  upsert: (suggestion: Suggestion) => void
  remove: (id: string) => void
}

function upsertById(list: Suggestion[], next: Suggestion): Suggestion[] {
  const index = list.findIndex((s) => s.id === next.id)
  if (index === -1) return [...list, next]
  const copy = list.slice()
  copy[index] = next
  return copy
}

export function useSuggestionList(params: SuggestionListParams | null): SuggestionListState {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const paramsRef = useRef(params)
  paramsRef.current = params

  const load = useCallback(async () => {
    if (!paramsRef.current) {
      setSuggestions([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      setSuggestions(await suggestionsApi.list(paramsRef.current))
      setError(null)
    } catch {
      setError('The suggestions could not be loaded.')
    } finally {
      setLoading(false)
    }
    // JSON key order is stable for the same object shape, so this is a legitimate cheap
    // dependency rather than a stale-closure risk.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(params)])

  useEffect(() => {
    void load()
  }, [load])

  const upsert = useCallback((suggestion: Suggestion) => {
    setSuggestions((current) => upsertById(current, suggestion))
  }, [])

  const remove = useCallback((id: string) => {
    setSuggestions((current) => current.filter((s) => s.id !== id))
  }, [])

  useEffect(() => {
    const onFullRecord = (envelope: WsEnvelope) => {
      // `suggestion.created`/`suggestion.updated` nest the record under `suggestion`
      // (`server/app/routers/suggestions.py`'s `_broadcast` calls) rather than sending it
      // flattened onto the envelope — unlike `suggestion.moved`/`.deleted`/`.status_changed`,
      // which are flat. Found by the M3 integration pass: the old flattened cast meant
      // `suggestion?.id` was always `undefined`, so this event silently did nothing — a
      // second tab never picked up a create/edit live, only on its next full reload.
      const payload = envelope.payload as { suggestion: Suggestion }
      if (payload.suggestion?.id) upsert(payload.suggestion)
    }
    const onMoved = (envelope: WsEnvelope) => {
      const payload = envelope.payload as Pick<Suggestion, 'id' | 'lat' | 'lng' | 'geometry_geojson'>
      setSuggestions((current) =>
        current.map((s) =>
          s.id === payload.id
            ? {
                ...s,
                ...payload,
                // distances/design.md D5: "the chip returns to its estimate state while the
                // new value is being fetched." The pin's old position made every real
                // duration stale; reverting to `pending` here (rather than waiting for a
                // refetch) is what makes that revert visible immediately instead of lagging
                // behind the recompute the server has just queued.
                distances: s.distances.map((d) =>
                  d.status === 'ok' ? { ...d, status: 'pending' as DistanceStatus, duration_s: null, is_estimate: true } : d,
                ),
              }
            : s,
        ),
      )
    }
    const onStatusChanged = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { id: string; status: SuggestionStatus }
      setSuggestions((current) =>
        current.map((s) => (s.id === payload.id ? { ...s, status: payload.status } : s)),
      )
    }
    const onDeleted = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { id: string }
      remove(payload.id)
    }
    // Owned by `voting-comments`/`distances`: this feature only renders their denormalised
    // fields, so it re-reads the one record rather than reimplementing their arithmetic.
    const refetchOne = async (id: string) => {
      try {
        upsert(await suggestionsApi.read(id))
      } catch {
        // A transient failure here just leaves the stale count on screen until the next
        // successful event or reconnect — never worth surfacing an error for.
      }
    }
    const onDerivedFieldChanged = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { suggestion_id?: string; id?: string }
      const id = payload.suggestion_id ?? payload.id
      if (id) void refetchOne(id)
    }
    // `distance.updated`'s payload shape is fixed by `distances/design.md` precisely enough
    // to patch the one family row in place — swapping the chip "as soon as its own answer
    // lands rather than waiting for the slowest sibling," which is that doc's own reason the
    // event is per-row rather than per-batch. A full refetch (the `onDerivedFieldChanged`
    // path other sibling-feature events still use) would reintroduce that wait.
    const onDistanceUpdated = (envelope: WsEnvelope) => {
      const payload = envelope.payload as {
        suggestion_id: string
        family_id: string
        status: DistanceStatus
        duration_s: number | null
        distance_m: number | null
        is_estimate: boolean
        computed_at: string | null
      }
      setSuggestions((current) =>
        current.map((s) => {
          if (s.id !== payload.suggestion_id) return s
          const index = s.distances.findIndex((d) => d.family_id === payload.family_id)
          if (index === -1) return s // a family this client has no row for yet — nothing to patch
          const nextDistances = s.distances.map((d, i) =>
            i === index
              ? {
                  ...d,
                  status: payload.status,
                  duration_s: payload.duration_s,
                  distance_m: payload.distance_m,
                  is_estimate: payload.is_estimate,
                  computed_at: payload.computed_at,
                }
              : d,
          )
          return { ...s, distances: nextDistances }
        }),
      )
    }

    const unsubscribes = [
      socket.subscribe('suggestion.created', onFullRecord),
      socket.subscribe('suggestion.updated', onFullRecord),
      socket.subscribe('suggestion.moved', onMoved),
      socket.subscribe('suggestion.status_changed', onStatusChanged),
      socket.subscribe('suggestion.deleted', onDeleted),
      socket.subscribe('suggestion.vote.updated', onDerivedFieldChanged),
      socket.subscribe('distance.updated', onDistanceUpdated),
      socket.subscribe('comment.created', onDerivedFieldChanged),
      socket.subscribe('comment.deleted', onDerivedFieldChanged),
      socket.subscribe('stage.changed', () => void load()),
      // After a reconnect the server replays nothing and says so — refetch and reconcile
      // by id, per `design.md`'s edge-case table.
      socket.subscribe('resync', () => void load()),
    ]
    return () => {
      for (const off of unsubscribes) off()
    }
  }, [load, upsert, remove])

  return { suggestions, loading, error, reload: load, upsert, remove }
}
