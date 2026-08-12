/**
 * The vote + comment endpoints, over foundation's `apiClient`. Coded to `design.md`'s
 * contract exactly, same discipline as `map-suggestions/api.ts`: this file is the wire
 * shape only, never a second copy of a permission or transition rule the server already
 * enforces.
 *
 * `categorySettingsApi` is deliberately **not** redefined here. `polls/api.ts` already calls
 * `GET /trip/category-settings` (`categoryApi.read`), which returns every category's mode
 * including the four suggestion types — `voting-comments/design.md` restates the same data
 * under a differently-shaped path (`/trips/{id}/category-settings`), but re-implementing a
 * second client for what is the same single-trip-scoped read would be two sources of truth
 * for one setting. This feature imports `polls`'s client instead; see the deviation note in
 * `plan/features/voting-comments/design.md`.
 */

import { api } from '../../app/apiClient'
import type { Comment, CommentSubjectType, PendingVotes, Thumb, VoteTally } from '../../app/types'

export type VoteInput = { score: number } | { thumb: Thumb }

export const votesApi = {
  upsert: (suggestionId: string, body: VoteInput) =>
    api.put<VoteTally>(`/suggestions/${suggestionId}/vote`, body),

  clear: (suggestionId: string) => api.del<VoteTally>(`/suggestions/${suggestionId}/vote`),

  read: (suggestionId: string) => api.get<VoteTally>(`/suggestions/${suggestionId}/votes`),

  pending: (tripId: string, excludeOwn = true) =>
    api.get<PendingVotes>(
      `/me/pending-votes?trip_id=${encodeURIComponent(tripId)}${excludeOwn ? '' : '&exclude_own=false'}`,
    ),
}

export const commentsApi = {
  list: (subjectType: CommentSubjectType, subjectId: string) =>
    api.get<Comment[]>(`/comments?subject_type=${subjectType}&subject_id=${subjectId}`),

  create: (subjectType: CommentSubjectType, subjectId: string, body: string) =>
    api.post<Comment>('/comments', { subject_type: subjectType, subject_id: subjectId, body }),

  update: (id: string, body: string) => api.patch<Comment>(`/comments/${id}`, { body }),

  remove: (id: string) => api.del<void>(`/comments/${id}`),

  undoDelete: (id: string) => api.post<Comment>(`/comments/${id}/undo-delete`),
}
