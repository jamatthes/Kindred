/**
 * The admin console's endpoints, over foundation's `apiClient` (CSRF, the one retry, the
 * typed error). Thin on purpose: every rule this feature has lives on the server, and a
 * client-side copy of one would be a second source of truth that drifts.
 *
 * The one thing worth noticing here is what is *not* in this file: a stage machine. The
 * console renders `can_advance_to` / `can_revert_to` / `blockers` as it receives them and
 * calls the single stage endpoint, which `holiday-stage` owns.
 */

import { api } from '../../app/apiClient'
import type {
  AdminMember,
  CategorySetting,
  Family,
  GoogleStatus,
  InstanceSettings,
  Organiser,
  StageTransition,
  Stats,
  TripAdmin,
  TripStage,
} from '../../app/types'

export type TripPatch = {
  name?: string
  start_date?: string | null
  end_date?: string | null
  timezone?: string
}

export const adminApi = {
  readTrip: () => api.get<TripAdmin>('/admin/trip'),
  patchTrip: (body: TripPatch) => api.patch<TripAdmin>('/admin/trip', body),
  stageHistory: () => api.get<StageTransition[]>('/admin/trip/stage-history'),

  /**
   * Owned by `holiday-stage`, not by this feature: there is exactly one endpoint that moves
   * a stage, and the console calls it rather than having its own. `reason: "revert"` is
   * required going backwards so a correction can never be an accidental payload.
   */
  changeStage: (tripId: string, stage: TripStage, revert = false) =>
    api.patch<{ id: string; stage: TripStage; changed_at: string }>(
      `/trips/${tripId}/stage`,
      revert ? { stage, reason: 'revert' } : { stage },
    ),

  categorySettings: () => api.get<CategorySetting[]>('/admin/category-settings'),
  putCategorySettings: (settings: { category: string; voting_mode: string }[]) =>
    api.put<CategorySetting[]>('/admin/category-settings', { settings }),

  overview: (q = '') =>
    api.get<{ families: Family[]; members: AdminMember[] }>(
      `/admin/overview${q ? `?q=${encodeURIComponent(q)}` : ''}`,
    ),
  resetPassword: (userId: string) =>
    api.post<{ temporary_password: string }>(`/admin/users/${userId}/reset-password`, {
      confirm: true,
    }),
  removeUser: (userId: string) => api.del<void>(`/admin/users/${userId}`),

  organisers: () => api.get<Organiser[]>('/admin/organisers'),
  appointOrganiser: (userId: string) =>
    api.post<Organiser>('/admin/organisers', { user_id: userId }),
  demoteOrganiser: (userId: string) => api.del<void>(`/admin/organisers/${userId}`),

  settings: () => api.get<InstanceSettings>('/admin/settings'),
  patchSettings: (body: Partial<InstanceSettings>) =>
    api.patch<InstanceSettings>('/admin/settings', body),

  googleStatus: () => api.get<GoogleStatus>('/admin/google-status'),
  runGoogleCheck: () => api.post<GoogleStatus>('/admin/google-status/check'),

  stats: () => api.get<Stats>('/admin/stats'),
}
