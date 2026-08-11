/**
 * The wire shapes foundation's endpoints return, mirroring the schemas in
 * `plan/features/foundation/design.md`. Kept in one file so a server change shows up as a
 * type error in every consumer at once.
 */

export type ThemePref = 'light' | 'dark' | 'system'

export type TripStage = 'planning' | 'holiday' | 'end'

/** `family` is null until the `families` feature ships. */
export type FamilyBrief = {
  id: string
  name: string
  color: number
  role: 'admin' | 'member'
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
  display_name: string
  is_platform_admin: boolean
  must_change_password: boolean
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
