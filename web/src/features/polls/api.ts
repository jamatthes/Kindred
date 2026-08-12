/**
 * The poll endpoints, over foundation's `apiClient`.
 *
 * Thin on purpose. Every rule this feature has — who may create, who may add an option, what
 * a closed poll refuses, whether a score or a thumb is expected — is enforced by the server,
 * and a client-side copy would be a second source of truth that drifts. What the UI decides
 * is what to *render*; what it may *do* it learns by being refused.
 */

import { api } from '../../app/apiClient'
import type {
  CategorySettingPublic,
  NudgeResult,
  Poll,
  PollComment,
  PollKind,
  PollResults,
  PollSummary,
  Thumb,
} from '../../app/types'

export type ScoreEntry = { option_id: string; score?: number; thumb?: Thumb }

export const pollsApi = {
  list: () => api.get<PollSummary[]>('/polls'),
  read: (id: string) => api.get<Poll>(`/polls/${id}`),
  results: (id: string) => api.get<PollResults>(`/polls/${id}/results`),

  create: (body: {
    title: string
    description?: string
    kind: PollKind
    allow_member_options: boolean
    options: { label: string; lat?: number; lng?: number }[]
  }) => api.post<Poll>('/polls', body),

  update: (id: string, body: { title?: string; description?: string; allow_member_options?: boolean }) =>
    api.patch<Poll>(`/polls/${id}`, body),

  remove: (id: string) => api.del<void>(`/polls/${id}`),

  close: (id: string) => api.post<Poll>(`/polls/${id}/close`, { confirm: true }),
  reopen: (id: string) => api.post<Poll>(`/polls/${id}/reopen`),

  addOption: (id: string, body: { label: string; lat?: number; lng?: number }) =>
    api.post<Poll['options'][number]>(`/polls/${id}/options`, body),

  removeOption: (id: string, optionId: string) =>
    api.del<void>(`/polls/${id}/options/${optionId}`),

  /**
   * Writes **the caller's own** scores. There is no `user_id` to pass — the endpoint has no
   * way to express writing somebody else's vote. Returns the recomputed results, so a save
   * needs no follow-up request.
   */
  putScores: (id: string, scores: ScoreEntry[]) =>
    api.put<PollResults>(`/polls/${id}/scores`, { scores }),

  clearScore: (id: string, optionId: string) =>
    api.del<PollResults>(`/polls/${id}/scores/${optionId}`),

  nudge: (id: string) => api.post<NudgeResult>(`/polls/${id}/nudge`),

  setDecision: (id: string, optionId: string) =>
    api.put<Poll>(`/polls/${id}/decision`, { option_id: optionId }),
  clearDecision: (id: string) => api.del<Poll>(`/polls/${id}/decision`),

  comments: (id: string) => api.get<PollComment[]>(`/polls/${id}/comments`),
  addComment: (id: string, body: string) =>
    api.post<PollComment>(`/polls/${id}/comments`, { body }),
  editComment: (commentId: string, body: string) =>
    api.patch<PollComment>(`/comments/${commentId}`, { body }),
  deleteComment: (commentId: string) => api.del<void>(`/comments/${commentId}`),
}

/**
 * The trip's voting mode, read rather than assumed (PL-4). Public to any member — the
 * admin-only variant carries vote counts this screen has no use for.
 */
export const categoryApi = {
  read: () => api.get<CategorySettingPublic[]>('/trip/category-settings'),
}
