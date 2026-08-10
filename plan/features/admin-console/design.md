# admin-console — Design

**Reads first:** `plan/architecture.md`, `plan/design-system.md`,
`plan/features/foundation/`, `plan/features/families/`, and `requirements.md` in this
directory.

## Data model

### `trips` (exists in `plan/architecture.md`)

`name`, `stage` (`planning` / `holiday` / `end`), `start_date`, `end_date` (nullable in
planning), `owner_user_id` (the main admin), `timezone`. This feature owns writes to all of
them.

### `trip_category_settings` (exists)

`trip_id`, `category` (`poll` / `region` / `accommodation` / `activity` / `meal`),
`voting_mode` (`score` / `thumbs`).

**PROPOSED ADDITION — unique index** on `(trip_id, category)`, plus seeding of all five rows
when a trip is created, so the mode is never unset and a read never has to invent a default.

Seed defaults: `poll` → `score` (the destination matrix is the origin use case),
`region` → `score`, `accommodation` → `score`, `activity` → `thumbs`, `meal` → `thumbs`.

### `settings` (exists)

Key/value platform config. Keys owned here: `instance_name`, `registration_open`,
`invite_only`.

**PROPOSED ADDITION — the `google_api_status` key**, holding a JSON value:

```
{"checked_at": "...", "checked_by": "<user_id>",
 "apis": {"geocoding": {"status": "ok"}, "distance_matrix": {"status": "denied", "detail": "REQUEST_DENIED"}, ...}}
```

Stored in `settings` rather than in a new table because it is a singleton, matching how
`settings` is already described ("singleton rows: instance name, registration open, etc.").

### PROPOSED ADDITION — `trip_stage_transitions`

Nothing in `plan/architecture.md` records who changed the stage or when, and AC-3/AC-4 both
require it.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `trip_id` | uuid fk | |
| `from_stage` | text | |
| `to_stage` | text | |
| `direction` | text | `forward` / `backward` |
| `changed_by` | uuid fk → users | |
| `created_at` | timestamptz | |

Small, append-only, never edited. This is the one piece of audit trail in v1 (see the
out-of-scope list).

### `users`, `families`, `family_members`, `sessions`

Read for the overview; `users.must_change_password` and `sessions.revoked_at` are written by
the password reset. `family_members` rows are deleted by user removal.

## REST endpoints

All under `/api/v1`. Every route in this feature carries `Depends(require_main_admin)`.
Mutating routes additionally carry a stage guard as noted.

### Trip

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/trip` | — | `TripAdminOut` | main admin |
| PATCH | `/admin/trip` | `{name?, start_date?, end_date?, timezone?}` | `TripAdminOut` | main admin + `require_stage("planning","holiday")` |
| POST | `/admin/trip/stage` | `{to_stage, confirm: true}` | `TripAdminOut` | main admin only — **no stage guard**, by design |
| GET | `/admin/trip/stage-history` | — | `[StageTransitionOut]` | main admin |

`TripAdminOut`: `{id, name, stage, start_date, end_date, timezone, owner_user_id, can_advance_to, can_revert_to, blockers: [str]}`.

`can_advance_to` is the single legal forward target or null; `can_revert_to` is the single
legal backward target or null; `blockers` lists machine-readable reasons the forward move is
unavailable (`missing_dates`). The frontend disables the control and shows the reason; the
backend enforces the same rule, so the two cannot drift.

`POST /admin/trip/stage` is deliberately exempt from `require_stage` — it is the carve-out
named in `plan/architecture.md` ("End stage rejects all mutations except admin stage-change").
It validates the transition itself: forward moves must follow
`planning → holiday → end`; backward moves must follow `end → holiday → planning`; anything
else is `409 illegal_transition`.

### Category voting modes

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/category-settings` | — | `[CategorySettingOut]` | main admin |
| PUT | `/admin/category-settings` | `[{category, voting_mode}]` | `[CategorySettingOut]` | main admin + `require_stage("planning","holiday")` |

`CategorySettingOut`: `{category, voting_mode, existing_vote_count}`. `existing_vote_count`
drives the "votes already exist" warning in AC-5 and is computed from `poll_scores` for
`poll` and from `suggestion_votes` for the four suggestion categories. Before those tables
have rows — or before those features exist — it reads zero.

A **read** of the current modes is needed by every voting UI, for every role. That read is
served by a separate non-admin route owned by this feature:

| Method | Path | Response | Guards |
|---|---|---|---|
| GET | `/trip/category-settings` | `[{category, voting_mode}]` | `require_member` |

### Members and families overview

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/overview` | `?q=` | `{families: [FamilyOut], members: [AdminMemberOut]}` | main admin |
| POST | `/admin/users/{id}/reset-password` | `{confirm: true}` | `{temporary_password}` | main admin |
| DELETE | `/admin/users/{id}` | — | `204` | main admin + `require_stage("planning","holiday")` |

`AdminMemberOut`: `{user_id, username, display_name, family: {id, name, color}|null, role, must_change_password, last_login_at, created_at, is_main_admin}`.

**PROPOSED ADDITION — `users.last_login_at`** (timestamptz, nullable). AC-6 asks whether a
member has ever logged in; nothing in the schema records it. Written by foundation's login
route once this column exists.

`reset-password` returns the generated password exactly once, in the response body only. It is
never logged, never stored in plaintext, and never re-retrievable. Generation: 4 short words
from a bundled wordlist joined by hyphens, which is easy to read aloud over the phone and
still long enough to satisfy the 10-character minimum.

`DELETE /admin/users/{id}` deletes the `family_members` row and revokes sessions; it does
**not** delete the `users` row, because votes, comments and suggestions reference it and AC-8
requires attribution to survive. The user record is retained with no family, which the
`require_member` dependency already treats as "not on this trip".

> NOTE: the endpoint is `DELETE` and the story says "remove", but the effect is removal from
> the trip, not account deletion. The response and the confirm dialog both say so explicitly
> so nobody is misled about what happened.

### Instance settings

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/settings` | — | `{instance_name, registration_open, invite_only}` | main admin |
| PATCH | `/admin/settings` | `{instance_name?, registration_open?, invite_only?}` | same | main admin |

No stage guard: instance settings are not trip data. `invite_only` accepts only `true` in v1;
`false` is rejected with `422` and a message that open registration is not implemented. The
field exists so the policy can widen later without a migration (see the NOTE in
`families/requirements.md`, FM-7).

### Google API status

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/google-status` | — | `GoogleStatusOut` | main admin |
| POST | `/admin/google-status/check` | — | `GoogleStatusOut` | main admin, rate-limited to 1/min |

`GET` reads the stored `settings` value and performs **no** external call. `POST` performs the
probe and stores the result.

`GoogleStatusOut`:

```
{checked_at: str|null, checked_by: str|null,
 browser_key_configured: bool, server_key_configured: bool,
 apis: [{name, status: "ok"|"denied"|"quota"|"unreachable"|"unchecked", detail: str|null, hint: str|null}]}
```

### Stats

| Method | Path | Response | Guards |
|---|---|---|---|
| GET | `/admin/stats` | `StatsOut` | main admin |

`StatsOut`: `{families, members, invites_open, polls_open, polls_closed, suggestions_by_status: {...}, comments, itinerary_items, checkins, notifications_unread}`.

Implemented as one query per count against tables that exist, with a hardcoded zero for tables
that do not yet exist at the current milestone. Each count is trip-scoped through `trip_id`.

## Google status probe

Lives in `services/google.py` next to the geocoder, behind the same interface pattern so tests
fake it.

Probe design — each API is checked with the cheapest possible request, and the result is
classified from the response status rather than from the payload:

| API | Probe | Key |
|---|---|---|
| Geocoding | Geocode a fixed, well-known string | server |
| Distance Matrix | One origin, one destination, both fixed coordinates | server |
| Directions | The same fixed pair | server |
| Places | A Place Details call for a fixed, stable `place_id` | server |
| Maps JS | Not probed server-side — reported as "configured / not configured" only | browser |

Classification: `OK`/`ZERO_RESULTS` → `ok`; `REQUEST_DENIED` → `denied`;
`OVER_QUERY_LIMIT` → `quota`; a transport error, timeout or non-200 → `unreachable`; no key
configured → `unchecked` with the detail `no_api_key`.

Maps JS cannot be verified from the server — it is a browser-side loader restricted by HTTP
referrer. Reporting it as merely "configured" is the honest answer; the UI says exactly that
rather than implying a check happened.

Total cost of one press: four requests. Rate-limited to one press per minute per instance,
reusing foundation's limiter keyed on a fixed string.

## WebSocket events

Emitted:

| Event | When | Payload | Consumers |
|---|---|---|---|
| `stage.changed` | any stage transition | `{from_stage, to_stage, trip: TripAdminOut-public-subset}` | **every** client — the whole app re-evaluates what is mutable |
| `trip.updated` | name, dates or timezone change | `{trip: {id, name, start_date, end_date, timezone}}` | app header, itinerary, invite preview |
| `category_settings.updated` | voting modes change | `[{category, voting_mode}]` | every voting UI |
| `member.removed` | a user is removed from the trip | `{family_id, user_id}` | reuses the `families` event — same payload, same handlers |

`stage.changed` is the reserved name from `plan/architecture.md`. `trip.updated` and
`category_settings.updated` are **PROPOSED ADDITIONs** to that list.

The removed or reset user's own socket additionally receives `session.revoked`
(**PROPOSED ADDITION**) via `send_user`, after which the server closes the socket. The client
routes to the login screen with a plain message rather than showing a wall of `401`s.

Consumed: nothing. This feature is the source of stage truth, not a consumer of it.

## UI behaviour

Per `plan/design-system.md`. The console is a **sectioned page**, not a modal and not a map
view — its content is configuration, which the reader compares and returns to, and
`design-system.md` reserves overlays for temporary interactions only.

Desktop: a single scrolling column at readable measure with a sticky section index on the
left, inside the standard app shell. This is the one place the 62/38 map split does not apply,
because there is no map dataset here. Mobile: the same sections stacked, with the index
collapsed into a jump menu.

### Section 1 — Trip

Form fields for name, start date, end date, timezone, each with all six field states. Explicit
`Save` (AC-2), disabled until something changes. Validation on blur; `end_date` before
`start_date` shows an error beneath the field. While in Planning, empty dates render as a
neutral "not decided yet" placeholder rather than an error, because that is the normal state.

### Section 2 — Stage

The current stage as a prominent label with a one-line description. Beneath it, one primary
action for the legal forward transition and a quieter, separated action for the backward
correction.

Forward confirm dialogs are real confirms, not undo — `design-system.md` reserves confirms for
admin-destructive actions, and freezing a trip qualifies. Each dialog names the consequences
concretely:

- **Planning → Holiday:** "Voting and suggestions stay open. The app switches to the
  now/next view on phones and check-ins become available."
- **Holiday → End:** "Everyone loses the ability to change anything. Polls, suggestions,
  comments and the itinerary become read-only. You can undo this from here if it was a
  mistake."

The confirm requires clicking a button labelled with the action ("Start the holiday", "Freeze
the trip"), never a bare "OK".

When `blockers` is non-empty the forward action is disabled and the reason appears next to it
in words ("Set start and end dates first"), with a link to the field above.

Stage history renders beneath as a small table: from, to, who, when.

### Section 3 — Voting modes

A five-row table: category, a one-line explanation, and a two-option segmented control
(`Score 1–10` / `Thumbs`). Changes stage locally and are committed with a `Save` action.

When `existing_vote_count > 0` for a changed row, saving first shows a confirm naming the
count: "12 votes have already been cast on activities. They will be kept but not shown while
thumbs voting is on."

### Section 4 — Families and members

Two tables using the shared table pattern: tri-state sort, sticky header and sticky first
column, tabular right-aligned numerics, full-row click targets, one search box filtering both.

Members table columns: display name, username, family (colour swatch plus name), role, status.
The status cell carries chips — `Must change password`, `Never logged in` — as icon plus text,
never colour alone.

Row actions: `Reset password`, `Remove from trip`. Both are admin-destructive and get real
confirm dialogs. The row for the main admin shows both actions disabled with a tooltip
explaining why.

Family rows link into the `families` feature's detail panel rather than re-implementing
editing here.

`Reset password` result: a copy-once block identical in pattern to the invite link — the
temporary password, a `Copy` action, and a plain line stating it is shown only now. A toast
confirms the copy.

### Section 5 — Instance

`instance_name` text field with `Save`. Registration policy as a radio group with `Invite
only` selected and the other options rendered disabled with a short note ("Not available in
this version"), per AC-9 — visible rather than hidden, so the roadmap is legible.

### Section 6 — Google APIs

A table: API name, key type (browser / server), status chip, detail, and when it was last
checked. A single `Run check` button above it, with the plain caption "This makes a few real
API calls." The button is disabled with a countdown for a minute after a press.

Status chips are icon plus word, never colour alone: `OK`, `Denied`, `Quota`, `Unreachable`,
`Not checked`. Failing rows show the hint text inline:

- `denied` → "The API may not be enabled in your Google Cloud project, or the key restriction
  may exclude this server's IP."
- `quota` → "The daily cap has been reached. Check the quota limits in Cloud Console."
- `unreachable` → "The server could not reach Google. Check the container's network access."
- `no_api_key` → "No key is configured in `.env`."

The Maps JS row shows `Configured` or `Not configured` with the plain caption that it cannot
be verified from the server.

If the check has never run, the table shows `Not checked` for everything and an empty-state
line — not a blank area.

### Section 7 — Stats

A grid of labelled numbers using tabular figures. No chart: these are unrelated single values,
and `design-system.md`'s honesty rules say the chart type must match the question — there is
no comparison or trend here, so plain numbers are the correct presentation. Zeroes are shown.

### Stage-change reception across the app

Every client consumes `stage.changed`. On `end`, the shell shows a persistent archive banner
("This trip has finished — everything is read-only") and mutating controls disappear rather
than failing on press. On a backward correction, controls reappear. The banner is a persistent
element, not a toast, because it is information that must stay visible.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| Non-admin opens `/admin` | Access screen in the UI; every endpoint returns `403 forbidden` |
| Forward transition without dates | `409 stage_blocked` with `blockers: ["missing_dates"]`; the control was already disabled |
| Illegal transition (e.g. planning → end) | `409 illegal_transition` |
| Two admins transition at once | Only one succeeds; the second gets `409 illegal_transition` because the from-stage no longer matches. Implemented as a conditional update on `stage = <expected>` |
| `end_date` before `start_date` | `422 validation_error` on the field |
| Timezone not a valid IANA name | `422 validation_error` |
| Editing trip settings while in End | `409 stage_forbidden` |
| Category mode changed with existing votes | Allowed; votes retained; the confirm named the count. No data is deleted |
| Category row missing (trip predates seeding) | `GET` seeds the missing row with its default on read, so the editor is never partially blank |
| Reset own password via the admin route | `409 cannot_target_self`; the profile page is the route |
| Remove self | `409 cannot_target_self` |
| Remove the last admin of a family | `409 last_family_admin`, matching `families` |
| Remove a user in the End stage | `409 stage_forbidden` — the archived membership record must not change |
| Reset a password for a user with no family | Allowed; account operations are not membership operations |
| Removed user has the app open | `member.removed` and `session.revoked` on their socket; the client routes to login with a plain message |
| Google check pressed twice inside a minute | `429 rate_limited` with `Retry-After`; the button shows the countdown |
| Google check with no server key | Returns immediately with `unchecked` / `no_api_key` for the server APIs and makes no network call |
| Google check partially fails | Each API is classified independently; one failure never masks another's success |
| Google check times out | That API is `unreachable`; the others still report. Per-request timeout of 5 seconds, so the whole press bounds at ~20 seconds |
| `settings` value is corrupt JSON | Treated as "never checked"; the row is overwritten on the next successful check |
| Stats query on a table that does not exist yet | The count reads zero; the console never errors because a later feature is unbuilt |
| Instance name set to empty | `422` — the login screen needs something to show |
| `invite_only` set to false | `422 not_implemented` with the explanatory message |

## Dependencies and hand-offs

- **Depends on `foundation`** for `require_main_admin`, `require_stage`, sessions and
  revocation, the rate limiter, the error envelope, and the WebSocket helpers.
- **Depends on `families`** for the family and member listing shapes, and for the
  `last_family_admin` rule which must behave identically in both features.
- **Provides to every voting feature** the `GET /trip/category-settings` read, which decides
  whether the UI renders a 1–10 scale or thumbs. `polls` and `voting-comments` must read it
  rather than assuming a mode.
- **Provides to every feature** the authoritative stage and the `stage.changed` broadcast.
  No other feature may write `trips.stage`.
- **Provides to `holiday-stage`** the transition into and out of `holiday`; that feature adds
  the on-the-day behaviour, not the machine itself.
