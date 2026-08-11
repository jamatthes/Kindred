/**
 * The wire shapes foundation's endpoints return, mirroring the schemas in
 * `plan/features/foundation/design.md`. Kept in one file so a server change shows up as a
 * type error in every consumer at once.
 */

export type ThemePref = 'light' | 'dark' | 'system'

export type TripStage = 'planning' | 'holiday' | 'end'

/** The viewer's own family, carried on `auth/me` so the shell knows it in one call. */
export type FamilyBrief = {
  id: string
  name: string
  color: number
  role: FamilyRole
}

/** The single active trip, carried on `auth/me` so the shell knows the stage in one call. */
export type TripBrief = {
  id: string
  name: string
  stage: TripStage
  start_date: string | null
  end_date: string | null
  timezone: string
}

export type User = {
  id: string
  username: string
  first_name: string
  last_name: string
  display_name: string
  avatar_url: string | null
  avatar_thumb_url: string | null
  /** Computed server-side so every badge of this person matches. */
  initials: string
  is_platform_admin: boolean
  /**
   * Trip-level roles. Carried here because the shell decides which controls to *render* and
   * cannot derive them — a viewer may have no family, so there is no `Member` of themselves
   * to read it from. What they may *do* is still the server's decision; hiding a control the
   * server would refuse is a courtesy, not a permission.
   */
  is_owner: boolean
  is_organiser: boolean
  must_change_password: boolean
  /**
   * **The onboarding gate.** Which top-level screen this session may see. The client routes
   * on this field alone and never recomputes the precedence from the individual flags —
   * that is what makes the forced password change and the setup screens impossible to
   * navigate around.
   */
  next_step: NextStep
  theme_pref: ThemePref
  locale: string
  family: FamilyBrief | null
  trip: TripBrief | null
}

export type LoginResponse = { user: User; csrf_token: string }

export type Preferences = { theme_pref: ThemePref; locale: string }

/** `GET /settings` — public, so the login screen can show the instance's own name. */
export type InstanceSettings = {
  instance_name: string
  registration_open: boolean
  invite_only: boolean
}

export type PresenceSnapshot = { online_user_ids: string[] }

// --- families -----------------------------------------------------------------------------
// The shapes `plan/features/families/design.md` specifies. Kept beside foundation's so a
// server change shows up as a type error in every consumer at once.

/** Which top-level screen this session may see. The client routes on this and nothing else. */
export type NextStep = 'change_password' | 'setup_trip' | 'setup_family' | 'app'

/** Family-level roles. Independent of the trip-level owner/organiser pair. */
export type FamilyRole = 'head' | 'spouse' | 'member'

export type GeocodeStatus = 'pending' | 'ok' | 'not_found' | 'error'

export type Member = {
  user_id: string
  username: string
  first_name: string
  last_name: string
  display_name: string
  avatar_url: string | null
  avatar_thumb_url: string | null
  /** Computed server-side, so every surface draws the same badge. */
  initials: string
  role: FamilyRole
  joined_at: string
  is_owner: boolean
  is_organiser: boolean
  /** The family's permission. */
  location_sharing_allowed: boolean
  /** Their own consent — null when the viewer is not entitled to know. */
  location_sharing_enabled: boolean | null
}

/** The coarse shape. Never carries an address; this is what the socket broadcasts. */
export type Family = {
  id: string
  name: string
  color: number
  member_count: number
  home_locality: string | null
  home_placed: boolean
  geocode_status: GeocodeStatus
  location_sharing_allowed: boolean
}

/**
 * `FamilyOut` plus members and policy. The four address keys are **absent** — not null — for
 * a caller who may not see them, which is why they are optional here rather than nullable:
 * `home_address === null` means "you may see it and there is none", and `undefined` means
 * "not yours to see". The UI must not collapse those two.
 */
export type FamilyDetail = Family & {
  members: Member[]
  member_location_default: boolean
  geocode_error: string | null
  home_address?: string | null
  home_lat?: number | null
  home_lng?: number | null
  home_geocoded_at?: string | null
}

export type InviteStatus = 'active' | 'used' | 'revoked' | 'expired'

export type Invite = {
  id: string
  created_by: string | null
  created_by_name: string | null
  created_at: string
  expires_at: string
  used_by: string | null
  used_by_name: string | null
  used_at: string | null
  revoked_at: string | null
  family: { id: string; name: string; color: number } | null
  status: InviteStatus
}

/** Returned once. `url` carries the raw token and cannot be fetched again. */
export type InviteCreated = {
  id: string
  url: string
  expires_at: string
  family: { id: string; name: string; color: number } | null
}

export type InvitePreview = {
  instance_name: string
  valid: boolean
  reason: 'expired' | 'used' | 'revoked' | 'unknown' | 'trip_ended' | 'family_missing' | null
  trip_name: string | null
  trip_stage: string | null
  mode: 'join' | 'create_family' | null
  family_name: string | null
}

export type InviteAccepted = { user: User; csrf_token: string; next_step: NextStep }
