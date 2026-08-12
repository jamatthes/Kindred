/**
 * The families endpoints, in one place, over foundation's `apiClient` (which already does
 * CSRF, the one retry after `csrf_invalid`, and the typed error).
 *
 * Thin on purpose: every rule this feature has — who may see an address, who may change a
 * role, what a spouse may not do — is enforced by the server, and a client-side copy of any
 * of it would be a second source of truth that drifts. What the UI decides is what to
 * *render*; what it may *do* it learns by being refused.
 */

import {
  ApiError,
  CSRF_COOKIE_NAME,
  CSRF_HEADER_NAME,
  api,
  readCookie,
} from '../../app/apiClient'
import type {
  Family,
  FamilyDetail,
  FamilyRole,
  Invite,
  InviteAccepted,
  InviteCreated,
  InvitePreview,
  Member,
  User,
} from '../../app/types'

export const familiesApi = {
  list: () => api.get<Family[]>('/families'),
  read: (id: string) => api.get<FamilyDetail>(`/families/${id}`),

  // REMOVED 2026-08-11 with the route: `create`, over the bare `POST /families`. It was the
  // only way to make a family nobody was in, which is what FM-1 now forbids. A family arrives
  // when its head accepts a new-family invite (`invitesApi.create` with `family_id: null`),
  // or when the owner names their own at setup.

  /**
   * The family setup screen's only write (FM-13), and now the only call in the client that
   * creates a family. Two kinds of caller reach it — someone who accepted a new-family
   * invite, and the owner during their own onboarding — with the same body.
   */
  createMine: (body: {
    name: string
    home_address?: string
    color?: number
    color_custom?: string
  }) => api.post<FamilyDetail>('/families/mine', body),

  update: (id: string, body: { name?: string; color?: number; color_custom?: string }) =>
    api.patch<FamilyDetail>(`/families/${id}`, body),

  /** `GET /families/palette` — the taken slots and whether all 24 are claimed, for the colour
   * picker (`web/src/design/ColorPicker.tsx`). Reachable before `POST /families/mine` even
   * exists as a route the caller may call — no `require_member` on the server side. */
  palette: () => api.get<{ taken_colors: number[]; exhausted: boolean }>('/families/palette'),

  remove: (id: string) => api.del<void>(`/families/${id}`),

  setHome: (id: string, home_address: string) =>
    api.put<FamilyDetail>(`/families/${id}/home`, { home_address }),

  clearHome: (id: string) => api.del<void>(`/families/${id}/home`),

  retryGeocode: (id: string) => api.post<FamilyDetail>(`/families/${id}/home/geocode`),

  setLocationPolicy: (
    id: string,
    body: { sharing_allowed?: boolean; member_default?: boolean },
  ) => api.patch<FamilyDetail>(`/families/${id}/location-policy`, body),

  updateMember: (
    familyId: string,
    userId: string,
    body: { role?: FamilyRole; location_sharing_allowed?: boolean },
  ) => api.patch<Member>(`/families/${familyId}/members/${userId}`, body),

  removeMember: (familyId: string, userId: string) =>
    api.del<void>(`/families/${familyId}/members/${userId}`),
}

export const invitesApi = {
  list: (familyId?: string) =>
    api.get<Invite[]>(familyId ? `/invites?family_id=${familyId}` : '/invites'),

  /** `family_id: null` is the new-family variant, and only an organiser may create it. */
  create: (body: { family_id: string | null; expires_in_hours: 24 | 168 | 720 }) =>
    api.post<InviteCreated>('/invites', body),

  revoke: (id: string) => api.post<void>(`/invites/${id}/revoke`),

  /** Public. Always 200 — an invalid token is `{valid: false}` with a reason. */
  preview: (token: string) =>
    api.get<InvitePreview>(`/invites/token/${encodeURIComponent(token)}`, {
      signalUnauthorized: false,
    }),

  accept: (
    token: string,
    body: {
      username: string
      first_name: string
      last_name: string
      password: string
      password_confirm: string
    },
  ) =>
    api.post<InviteAccepted>(`/invites/token/${encodeURIComponent(token)}/accept`, body, {
      signalUnauthorized: false,
    }),
}

export const profileApi = {
  update: (body: { first_name?: string; last_name?: string; display_name?: string }) =>
    api.patch<User>('/me', body),

  removeAvatar: () => api.del<User>('/me/avatar'),

  /**
   * `fetch` directly rather than through `apiClient`: this is the one request in the app
   * with a `multipart/form-data` body, and the client's job is to JSON-encode. Teaching it
   * a second body format for one call site would be more machinery than the call is worth —
   * so the CSRF header is read the same way, from the same cookie, right here.
   */
  uploadAvatar: async (file: File): Promise<User> => {
    const form = new FormData()
    form.append('file', file)
    const csrf = readCookie(CSRF_COOKIE_NAME)
    const response = await fetch('/api/v1/me/avatar', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: csrf ? { [CSRF_HEADER_NAME]: csrf } : {},
      body: form,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      const detail = body?.detail
      throw new ApiError(
        response.status,
        typeof detail?.code === 'string' ? detail.code : 'unexpected_error',
        typeof detail?.message === 'string'
          ? detail.message
          : 'That picture could not be saved.',
      )
    }
    return (await response.json()) as User
  },
}
