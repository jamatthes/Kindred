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
  /** Exactly one of `color` / `color_custom` is set. Resolve with `familyColor()`, never
   * branch on which is present at the call site. */
  color: number | null
  color_custom: string | null
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
  /** Exactly one of `color` / `color_custom` is set (2026-08-11 palette ruling — the
   * palette grew from 8 to 24 slots, and a 25th+ family may hold a free-choice hex
   * instead). Resolve with `familyColor(family)`; never branch on which is present. */
  color: number | null
  color_custom: string | null
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
  family: { id: string; name: string; color: number | null; color_custom: string | null } | null
  status: InviteStatus
}

/** Returned once. `url` carries the raw token and cannot be fetched again. */
export type InviteCreated = {
  id: string
  url: string
  expires_at: string
  family: { id: string; name: string; color: number | null; color_custom: string | null } | null
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

// --- admin console ------------------------------------------------------------------------
// Mirrors `server/app/schemas/admin.py`. The stage affordances are computed server-side and
// arrive as answers: the console renders them, and never works out legality itself.

export type TripAdmin = {
  id: string
  name: string
  stage: TripStage
  start_date: string | null
  end_date: string | null
  timezone: string
  owner_user_id: string | null
  /** The single legal forward target, or null when there is none or a blocker stands. */
  can_advance_to: TripStage | null
  can_revert_to: TripStage | null
  /** Machine-readable reasons the forward move is unavailable, e.g. `missing_dates`. */
  blockers: string[]
  /** AC-0: name and timezone set. The same predicate foundation's gate reads. */
  setup_complete: boolean
}

export type StageTransition = {
  from_stage: string
  to_stage: string
  direction: 'forward' | 'backward'
  changed_by: { user_id: string | null; display_name: string | null } | null
  created_at: string
}

export type VotingCategory = 'poll' | 'region' | 'accommodation' | 'activity' | 'meal'
export type VotingMode = 'score' | 'thumbs'

export type CategorySetting = {
  category: VotingCategory
  voting_mode: VotingMode
  existing_vote_count: number
}

export type AdminMember = {
  user_id: string
  username: string
  first_name: string
  last_name: string
  display_name: string
  initials: string
  avatar_thumb_url: string | null
  family: Family | null
  family_role: FamilyRole | null
  /** Three independent facts, not one enum — the two kinds of role are independent. */
  is_owner: boolean
  is_organiser: boolean
  must_change_password: boolean
  /** Null means never. */
  last_login_at: string | null
  created_at: string
}

export type Organiser = {
  user_id: string
  display_name: string
  initials: string
  avatar_thumb_url: string | null
  family: Family | null
  family_role: FamilyRole | null
  granted_by: { user_id: string | null; display_name: string | null } | null
  created_at: string
}

export type GoogleApiStatus =
  | 'ok'
  | 'denied'
  | 'quota'
  | 'unreachable'
  | 'unchecked'
  | 'configured'

export type GoogleApiRow = {
  name: string
  key_type: 'browser' | 'server'
  status: GoogleApiStatus
  detail: string | null
  hint: string | null
}

export type GoogleStatus = {
  checked_at: string | null
  checked_by: string | null
  browser_key_configured: boolean
  server_key_configured: boolean
  apis: GoogleApiRow[]
}

export type Stats = {
  families: number
  members: number
  invites_open: number
  polls_open: number
  polls_closed: number
  suggestions_by_status: {
    proposed: number
    approved: number
    scheduled: number
    rejected: number
  }
  comments: number
  itinerary_items: number
  checkins: number
  notifications_unread: number
}

// --- polls --------------------------------------------------------------------------------
// The shapes `plan/features/polls/design.md` specifies. Every computed number — average,
// spread, split and close flags, ranks, completion, the insight sentence — is produced
// server-side and simply rendered here. The frontend never recomputes any of it, so the
// table, the charts and the map cannot disagree.

export type PollKind = 'score_matrix' | 'options'
export type PollStatus = 'open' | 'closed'
export type Completion = 'none' | 'partial' | 'complete'
export type Thumb = 'up' | 'down'

export type PollOption = {
  id: string
  label: string
  lat: number | null
  lng: number | null
  place_id: string | null
  sort: number
  created_by: string | null
  suggestion_id: string | null
  /** Computed per caller — the client never derives permission. */
  can_delete: boolean
}

export type GroupCompletion = {
  complete: number
  partial: number
  none: number
  /** The membership, not the respondents — the denominator for "3 of 9 haven't voted". */
  total: number
}

export type PollDecision = { option_id: string; label: string }

export type PollSummary = {
  id: string
  title: string
  kind: PollKind
  status: PollStatus
  option_count: number
  comment_count: number
  my_completion: Completion
  group_completion: GroupCompletion
  decision: PollDecision | null
  created_at: string
}

export type Poll = PollSummary & {
  description: string | null
  allow_member_options: boolean
  options: PollOption[]
  voting_mode: VotingMode
  closed_at: string | null
  decided_at: string | null
  decided_by: string | null
  can_nudge: boolean
  next_nudge_at: string | null
  /** False at M2 — `map-suggestions` has not shipped, so the action is never rendered. */
  can_seed_region: boolean
}

export type PollScore = {
  user_id: string
  display_name: string
  family_id: string | null
  family_color: number | null
  family_color_custom: string | null
  score: number | null
  thumb: string | null
}

export type OptionResult = {
  option_id: string
  label: string
  lat: number | null
  lng: number | null
  /** Null when nobody has scored. **Never 0.0** — a silence is not a zero. */
  average: number | null
  response_count: number
  /** Null below two responses: the spread of one number is undefined, not zero. */
  spread: number | null
  is_split: boolean
  is_close: boolean
  rank: number
  scores: PollScore[]
  up_count: number
  down_count: number
  none_count: number
}

export type MemberResult = {
  user_id: string
  display_name: string
  family_id: string | null
  family_color: number | null
  family_color_custom: string | null
  completion: Completion
}

export type NonResponder = { user_id: string; display_name: string; completion: Completion }

export type PollResults = {
  poll_id: string
  voting_mode: VotingMode
  status: PollStatus
  options: OptionResult[]
  members: MemberResult[]
  non_responders: { count: number; total: number; users: NonResponder[] }
  /** Generated server-side so every view carries the same sentence. */
  insight: string
}

export type PollComment = {
  id: string
  subject_type: string
  subject_id: string
  author_id: string | null
  author_name: string
  family_id: string | null
  family_color: number | null
  family_color_custom: string | null
  body: string
  created_at: string
  edited_at: string | null
  can_edit: boolean
  can_delete: boolean
}

export type NudgeResult = { nudged: number; next_nudge_at: string | null; message: string }

/** `GET /trip/category-settings` — the public read every member may make. */
export type CategorySettingPublic = { category: VotingCategory; voting_mode: VotingMode }

// --- map-suggestions ------------------------------------------------------------------------
// The shapes `plan/features/map-suggestions/design.md` specifies. The HARD INVARIANT there
// governs this file too: nothing Google-sourced beyond `place_id` is ever a field here that
// gets sent back to the server. `vote_summary`/`comment_count`/`distances` are denormalised
// into the suggestion by the server (owned by `voting-comments`/`distances`); this feature
// only ever renders them.

export type SuggestionType = 'region' | 'accommodation' | 'activity' | 'meal'
export type SuggestionStatus = 'proposed' | 'shortlisted' | 'approved' | 'scheduled' | 'rejected'

/** The GeoJSON `Feature` encoding from `design.md` > "Region geometry encoding". Coordinates
 * are `[lng, lat]` — GeoJSON order — the one place in the codebase that order is legal; the
 * conversion to our `LatLng` happens once, in `features/map-suggestions/geometry.ts`. */
export type RegionGeometry =
  | {
      type: 'Feature'
      geometry: { type: 'Point'; coordinates: [number, number] }
      properties: { shape: 'circle'; radius_m: number; boundary_source?: 'osm' | 'drawn' }
    }
  | {
      type: 'Feature'
      geometry: { type: 'Polygon'; coordinates: [number, number][][] }
      properties: { shape: 'polygon'; boundary_source?: 'osm' | 'drawn'; osm_relation_id?: number }
    }

export type PlaceSnapshot = { name: string; address: string }

export type SuggestionAuthor = {
  user_id: string
  display_name: string
  family_id: string | null
  family_color: number | null
  /** Not in the `design.md` response sketch, but every other author/member shape in this
   * codebase carries both palette-slot and overflow-custom colour (`familyColor()` needs
   * both); optional so the UI degrades if the server does not send it yet. */
  family_color_custom?: string | null
}

export type SuggestionVoteSummary = {
  mode: VotingMode
  count: number
  average: number | null
  up: number | null
  down: number | null
  my_vote: number | 'up' | 'down' | null
}

/** One family's distance to one suggestion — `distances/design.md`'s `DistanceOut` shape,
 * reused verbatim on `Suggestion.distances` per that doc's own note: "`map-suggestions`'
 * `GET /api/v1/suggestions` already embeds a `distances` array per item for exactly this
 * reason" (avoiding a distance request per row). `status` is the DB's three real values
 * (`pending`/`ok`/`no_route`/`failed`) widened with the presentation-only `no_home` — a
 * family lacking a geocoded home, computed server-side, never stored. */
export type DistanceStatus = 'pending' | 'ok' | 'no_route' | 'failed' | 'no_home'

export type DistanceOut = {
  family_id: string
  family_name: string
  family_color: number | null
  family_color_custom?: string | null
  status: DistanceStatus
  duration_s: number | null
  distance_m: number | null
  /** True for a haversine fallback (`status: 'pending'`) — never true alongside a real
   * `status: 'ok'` row. An estimate never carries `duration_s`: inventing a driving
   * duration from a straight line would violate design-system.md's honesty rules. */
  is_estimate: boolean
  computed_at: string | null
}

export type Suggestion = {
  id: string
  type: SuggestionType
  title: string
  notes: string | null
  status: SuggestionStatus
  created_by: SuggestionAuthor
  lat: number
  lng: number
  geometry_geojson: RegionGeometry | null
  place_id: string | null
  place_snapshot: PlaceSnapshot | null
  external_url: string | null
  vote_summary: SuggestionVoteSummary | null
  comment_count: number
  distances: DistanceOut[]
  /** One level only, per `design.md` — a grouped child never has its own `children`. */
  children: Suggestion[]
  created_at: string
  updated_at: string
}

export type SuggestionSortField = 'votes' | 'distance' | 'category' | 'created'
export type SuggestionSortDir = 'asc' | 'desc'

export type SuggestionCreateInput = {
  /** Not sent to the server: `POST /suggestions`'s real schema (`SuggestionCreate`, `extra
   * = "forbid"`) derives the trip from the session's single active trip and has no
   * `trip_id` field at all — the M3 web build's mock contract (design.md's own written
   * shape) included one, and the real backend's implementation dropped it. Found by the
   * M3 integration pass's live Playwright smoke as a `422 validation_error`. Kept here,
   * optional, only so a caller can still thread the id through for its own purposes
   * without the type forcing a value that must not be serialised. */
  trip_id?: string
  type: SuggestionType
  title: string
  notes?: string
  lat: number
  lng: number
  geometry_geojson?: RegionGeometry
  place_id?: string
  place_snapshot?: PlaceSnapshot
  external_url?: string
}

export type SuggestionUpdateInput = Partial<
  Pick<
    SuggestionCreateInput,
    'title' | 'notes' | 'type' | 'external_url' | 'lat' | 'lng' | 'geometry_geojson' | 'place_id' | 'place_snapshot'
  >
>

// --- voting-comments ------------------------------------------------------------------------
// The shapes `plan/features/voting-comments/design.md` specifies. Every computed number —
// average, distribution, up/down/none, can_edit/can_delete — is produced server-side and
// simply rendered here, same rule as polls' results types above.

export type VoterEntry = {
  user_id: string
  display_name: string
  family_id: string | null
  family_color: number | null
  family_color_custom?: string | null
  score?: number | null
  thumb?: Thumb | null
}

export type NotVotedEntry = { user_id: string; display_name: string; family_id: string | null }

/** `PUT`/`DELETE .../vote` and `GET .../votes` response shape. `my_vote` is per-recipient —
 * never present in the `suggestion.vote.updated` broadcast, which is why every consumer of
 * that event merges the broadcast fields into its own locally-known `my_vote` rather than
 * overwriting it (`design.md` > WebSocket events). */
export type VoteTally = {
  mode: VotingMode
  count: number
  eligible_count: number
  average: number | null
  distribution: number[] | null
  up: number | null
  down: number | null
  none: number | null
  my_vote: { score?: number; thumb?: Thumb } | null
  voters: VoterEntry[]
  not_voted: NotVotedEntry[]
}

export type PendingVotes = { count: number; suggestion_ids: string[] }

export type CommentSubjectType = 'suggestion' | 'poll' | 'itinerary_item'

export type CommentAuthor = {
  user_id: string
  display_name: string
  family_id: string | null
  family_color: number | null
  family_color_custom?: string | null
}

export type Comment = {
  id: string
  /** Not in `design.md`'s `GET /comments` response sketch, but assumed present on the
   * `comment.created`/`.updated` WS payload (the same doc's `comment.deleted` payload does
   * carry them) — a client cannot otherwise route a live comment to the right open thread.
   * Optional so the type still matches the documented REST shape exactly. */
  subject_type?: CommentSubjectType
  subject_id?: string
  author: CommentAuthor
  body: string
  mentions: string[]
  edited_at: string | null
  created_at: string
  can_edit: boolean
  can_delete: boolean
}

export type LinkPreview = {
  title?: string
  description?: string
  image_url?: string
  site_name?: string
  /** Airbnb-aware extraction extras (`design.md` "Airbnb-aware extraction"). */
  facts?: string
  locality?: string
  lat?: number
  lng?: number
  capacity?: number
}

// --- distances ------------------------------------------------------------------------------
// The shapes `plan/features/distances/design.md` specifies. `DistanceOut` itself lives with
// `Suggestion` above (reused verbatim on `Suggestion.distances`); these are the standalone
// endpoints' envelopes — used when the client needs distances without a full suggestion
// fetch, e.g. after switching the sort perspective to another family.

export type SuggestionDistancesOut = { suggestion_id: string; distances: DistanceOut[] }

/** `GET /api/v1/distances` bulk response: one trip's suggestions, keyed by id. */
export type BulkDistancesOut = Record<string, DistanceOut[]>

/** `trip_id` is likewise never sent — `POST /distances/recompute`'s real `RecomputeIn`
 * schema (`extra = "forbid"`) has only `suggestion_id`; same session-derived-trip mismatch
 * as `SuggestionCreateInput.trip_id`, found the same way. Optional here for the same
 * reason: a caller may still want to thread the id through without it being serialised. */
export type RecomputeRequest = { trip_id?: string; suggestion_id?: string }

/** Returned *before* the background work runs, so the UI can state the cost
 * (`design.md` D7) rather than discover it after the fact. */
export type RecomputeResult = { queued_pairs: number; estimated_api_calls: number }
