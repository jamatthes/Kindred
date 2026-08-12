/**
 * The distances endpoints, over foundation's `apiClient`. Coded to `design.md`'s contract
 * exactly — same discipline as every other M3 feature's client: wire shape only, no rule
 * this feature's own server half already enforces (which pairs are stale, what a force
 * recompute costs, who may trigger one).
 */

import { api } from '../../app/apiClient'
import type {
  BulkDistancesOut,
  RecomputeRequest,
  RecomputeResult,
  SuggestionDistancesOut,
} from '../../app/types'

export type BulkDistancesParams = {
  trip_id: string
  suggestion_ids?: string[]
  /** Defaults server-side to the caller's own family (`design.md`) — omit for "mine". */
  family_id?: string
}

function toQuery(params: BulkDistancesParams): string {
  const q = new URLSearchParams()
  q.set('trip_id', params.trip_id)
  for (const id of params.suggestion_ids ?? []) q.append('suggestion_ids', id)
  if (params.family_id) q.set('family_id', params.family_id)
  return q.toString()
}

export const distancesApi = {
  forSuggestion: (suggestionId: string) =>
    api.get<SuggestionDistancesOut>(`/suggestions/${suggestionId}/distances`),

  bulk: (params: BulkDistancesParams) => api.get<BulkDistancesOut>(`/distances?${toQuery(params)}`),

  // `trip_id` is a query param on every GET above (harmless if unused server-side — FastAPI
  // ignores an extra query param it never declared) but `POST /distances/recompute`'s body
  // schema is `extra = "forbid"` and has no `trip_id` field at all (see `RecomputeRequest`'s
  // own comment, app/types.ts) — stripped here, centrally, so no caller has to remember to
  // omit it themselves.
  recompute: ({ suggestion_id }: RecomputeRequest) =>
    api.post<RecomputeResult>('/distances/recompute', { suggestion_id }),
}
