/**
 * The suggestion + link-preview endpoints, over foundation's `apiClient`. Coded to the
 * contract in `plan/features/map-suggestions/design.md` exactly — paths, params, payload
 * shapes — so the real backend drops in with no change here once it lands.
 *
 * As thin as `polls/api.ts`: this file's job is the wire shape, not the rules. Whether a
 * status transition is legal, who may edit whose suggestion, whether the stage allows a
 * write — all server-enforced; this client learns the answer from the response, never
 * precomputes it.
 */

import { api } from '../../app/apiClient'
import type {
  LinkPreview,
  Suggestion,
  SuggestionCreateInput,
  SuggestionSortDir,
  SuggestionSortField,
  SuggestionStatus,
  SuggestionType,
  SuggestionUpdateInput,
} from '../../app/types'

export type SuggestionListParams = {
  trip_id: string
  type?: SuggestionType[]
  status?: SuggestionStatus[]
  family_id?: string[]
  sort?: `${SuggestionSortField}_${SuggestionSortDir}`
  group?: boolean
  include_rejected?: boolean
}

function toQuery(params: SuggestionListParams): string {
  const q = new URLSearchParams()
  q.set('trip_id', params.trip_id)
  for (const t of params.type ?? []) q.append('type', t)
  for (const s of params.status ?? []) q.append('status', s)
  for (const f of params.family_id ?? []) q.append('family_id', f)
  if (params.sort) q.set('sort', params.sort)
  if (params.group !== undefined) q.set('group', String(params.group))
  if (params.include_rejected !== undefined) q.set('include_rejected', String(params.include_rejected))
  return q.toString()
}

export const suggestionsApi = {
  list: (params: SuggestionListParams) => api.get<Suggestion[]>(`/suggestions?${toQuery(params)}`),

  read: (id: string) => api.get<Suggestion>(`/suggestions/${id}`),

  create: (body: SuggestionCreateInput) => api.post<Suggestion>('/suggestions', body),

  update: (id: string, body: SuggestionUpdateInput) => api.patch<Suggestion>(`/suggestions/${id}`, body),

  remove: (id: string) => api.del<void>(`/suggestions/${id}`),

  setStatus: (id: string, status: SuggestionStatus) =>
    api.patch<Suggestion>(`/suggestions/${id}/status`, { status }),

  linkPreview: (url: string) => api.post<LinkPreview | undefined>('/link-preview', { url }),
}
