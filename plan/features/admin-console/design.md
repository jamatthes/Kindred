# admin-console — Design

**Reads first:** `plan/architecture.md`, `plan/design-system.md`,
`plan/features/foundation/`, `plan/features/families/`, and `requirements.md` in this
directory.

> NOTE: role hierarchy updated 2026-08-11 — "main admin" split into **owner** (`trips.owner_user_id`,
> the only role that manages organisers) and **organiser** (`trip_organisers`, every other
> cross-family power). "Family admin" is now **head of family** / **spouse**
> (`family_members.role`), which this feature reads but does not manage. See
> `plan/overview.md`'s Roles section and decision log.

## Data model

### `trips` (exists in `plan/architecture.md`)

`name`, `stage` (`planning` / `holiday` / `end`), `start_date`, `end_date` (nullable in
planning), `owner_user_id` (the owner), `timezone`. This feature owns writes to all of
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

### `trip_organisers` (owned by `families`; this feature writes to it)

`trip_id`, `user_id`, `granted_by` (the owner), `created_at`. One row per organiser. This
feature is the only place that writes it — Section 8 (Organisers) appoints and demotes by
inserting and deleting rows here. There is no `role` column: membership in this table *is* the
organiser role, and removing the row is the entire demotion.

## REST endpoints

All under `/api/v1`. Every route in this feature carries `Depends(require_organiser)` (owner OR
organiser) except the Organisers section's own routes, which carry `Depends(require_owner)`.
Mutating routes additionally carry a stage guard as noted.

### Trip

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/trip` | — | `TripAdminOut` | `require_organiser` |
| PATCH | `/admin/trip` | `{name?, start_date?, end_date?, timezone?}` | `TripAdminOut` | `require_organiser` + `require_stage("planning","holiday")` |
| — | *(stage changes)* | | | see below — the console calls `PATCH /trips/{trip_id}/stage`, owned by `holiday-stage` |
| GET | `/admin/trip/stage-history` | — | `[StageTransitionOut]` | `require_organiser` |

`TripAdminOut`: `{id, name, stage, start_date, end_date, timezone, owner_user_id, can_advance_to, can_revert_to, blockers: [str], setup_complete: bool}`.

`setup_complete` is `name is not null and name != "" and timezone is not null`. It is the same
predicate foundation's `next_step` uses to decide `setup_trip` (F-13), computed in one place and
exposed so the console and the gate cannot drift. It is deliberately **not** `start_date` and
`end_date`: those are legitimately unknown during Planning, and requiring them to finish setup
would block the owner on a decision the trip has not made yet.

### Trip setup (AC-0)

The first-login setup screen writes through the endpoint that already exists — `PATCH
/admin/trip` — rather than a parallel one. There is no separate "setup" route, because a setup
screen that wrote through a different code path would be a second place for validation to drift.

The only additions AC-0 needs:

- The screen is reached solely through foundation's `next_step: "setup_trip"`. It is not a
  route the owner can navigate to afterwards; once `setup_complete` is true the gate
  returns `app` and the same fields are edited in Section 1 of the console. The gate reaches
  this screen for the owner only — organisers never see `next_step: "setup_trip"`, matching
  `requirements.md`'s AC-0.
- `PATCH /admin/trip` keeps `require_stage("planning","holiday")`. A trip that has never been
  set up is by definition in Planning, so the guard is satisfied and no exemption is needed.
- The seeded trip is created with `name = ''` and `timezone` from the container's `TZ`. The
  empty name is what makes `setup_complete` false on a fresh install; seeding a placeholder like
  "My trip" would let the gate be skipped silently and leave the placeholder in the header.

> NOTE: `TZ` gives the setup screen a sensible default but does not satisfy `setup_complete` on
> its own — the name still must be set. This is deliberate: the timezone has a defensible
> default and the trip's name does not.

`can_advance_to` is the single legal forward target or null; `can_revert_to` is the single
legal backward target or null; `blockers` lists machine-readable reasons the forward move is
unavailable (`missing_dates`). The frontend disables the control and shows the reason; the
backend enforces the same rule, so the two cannot drift.

**Stage transitions have exactly one endpoint** (ruling 2026-08-11, resolving a duplicate):
`PATCH /api/v1/trips/{trip_id}/stage`, owned and implemented by `holiday-stage`
(`require_organiser`, deliberately exempt from `require_stage` — the carve-out named in
`plan/architecture.md`). It validates transitions itself: forward `planning → holiday → end`,
backward `end → holiday → planning`, anything else `409 illegal_transition`. The console's
stage stepper (Section 2) calls that endpoint; the previously sketched
`POST /admin/trip/stage` does not exist. `can_advance_to`/`can_revert_to`/`blockers` on
`TripAdminOut` remain this feature's — the console computes the affordances, holiday-stage
executes the change.

### Category voting modes

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/category-settings` | — | `[CategorySettingOut]` | `require_organiser` |
| PUT | `/admin/category-settings` | `[{category, voting_mode}]` | `[CategorySettingOut]` | `require_organiser` + `require_stage("planning","holiday")` |

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
| GET | `/admin/overview` | `?q=` | `{families: [FamilyOut], members: [AdminMemberOut]}` | `require_organiser` |
| POST | `/admin/users/{id}/reset-password` | `{confirm: true}` | `{temporary_password}` | `require_organiser` + **protected-target rule** |
| DELETE | `/admin/users/{id}` | — | `204` | `require_organiser` + `require_stage("planning","holiday")` + **protected-target rule** |

**Protected-target rule** (ruling 2026-08-11): when the target of a reset or removal is the
**owner or another organiser**, `require_organiser` is not enough — the caller must be the
owner (`403 target_protected` otherwise). Nobody resets the owner's password or removes the
owner at all (`409 cannot_target_owner`); an organiser targeting a fellow organiser is refused
for the same reason the organiser list itself is owner-only. Ordinary members remain
organiser-manageable.

`AdminMemberOut`: `{user_id, username, first_name, last_name, display_name, initials, avatar_thumb_url, family: {id, name, color}|null, family_role, is_owner, is_organiser, must_change_password, last_login_at, created_at}`.

`family_role` is the `family_members.role` value (`head` / `spouse` / `member`) or `null` for
someone with no family. `is_owner` and `is_organiser` are independent booleans, not a single
enum, because the two kinds of role are independent (`plan/overview.md`'s Roles section) — a
person can be `is_organiser: true` and `family_role: "head"` at once. The overview table
renders these three fields into the single "Owner / Organiser / Head / Spouse / Member" role
column described in `requirements.md` AC-6, showing every applicable label (e.g. an organiser
who heads their family shows "Organiser · Head"). `is_main_admin` is retired along with the
role it named.

The identity fields come from `families`' shared serialiser, not from a second implementation
here — the console must show the same badge and the same name as the map and the member list.

`AdminMemberOut` deliberately carries **no** location-sharing fields. The owner or an organiser
edits those through the family panel in `families` (FM-15), which is the same rule the rest of
this console follows: family editing lives there and is linked to, not duplicated here.

**PROPOSED ADDITION — `users.last_login_at`** (timestamptz, nullable). AC-6 asks whether a
member has ever logged in; nothing in the schema records it. Written by foundation's login
route once this column exists.

`reset-password` returns the generated password exactly once, in the response body only. It is
never logged, never stored in plaintext, and never re-retrievable. Generation: 4 short words
from a bundled wordlist joined by hyphens, which is easy to read aloud over the phone.

> NOTE: the four-word format is kept even though F-5's length minimum was removed
> (2026-08-11). A *generated* credential costs the recipient nothing to be long, and it is
> handed over on a phone call rather than typed from memory — so the reasoning that justified
> dropping the minimum for user-chosen passwords does not apply here.

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
| GET | `/admin/settings` | — | `{instance_name, registration_open, invite_only}` | `require_organiser` |
| PATCH | `/admin/settings` | `{instance_name?, registration_open?, invite_only?}` | same | `require_owner` |

Reading is organiser-visible; **writing is owner-only** (ruling 2026-08-11): instance
settings are platform-level, not trip-level, so they sit outside the "cross-family trip
powers" an organiser holds. The console renders the section read-only with an explanatory
caption for organisers.

No stage guard: instance settings are not trip data. `invite_only` accepts only `true` in v1;
`false` is rejected with `422` and a message that open registration is not implemented. The
field exists so the policy can widen later without a migration (see the NOTE in
`families/requirements.md`, FM-7).

### Google API status

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/google-status` | — | `GoogleStatusOut` | `require_organiser` |
| POST | `/admin/google-status/check` | — | `GoogleStatusOut` | `require_organiser`, rate-limited to 1/min |

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
| GET | `/admin/stats` | `StatsOut` | `require_organiser` |

`StatsOut`: `{families, members, invites_open, polls_open, polls_closed, suggestions_by_status: {...}, comments, itinerary_items, checkins, notifications_unread}`.

Implemented as one query per count against tables that exist, with a hardcoded zero for tables
that do not yet exist at the current milestone. Each count is trip-scoped through `trip_id`.

### Organisers (AC-13)

| Method | Path | Request | Response | Guards |
|---|---|---|---|---|
| GET | `/admin/organisers` | — | `[OrganiserOut]` | `require_organiser` |
| POST | `/admin/organisers` | `{user_id}` | `201` `OrganiserOut` | `require_owner` |
| DELETE | `/admin/organisers/{user_id}` | — | `204` | `require_owner` |

`OrganiserOut`: `{user_id, display_name, initials, avatar_thumb_url, family: {id, name, color}|null, family_role, granted_by: {user_id, display_name}, created_at}`.

`GET` is readable by any organiser (and the owner) so the console can show "who else can do
what I can do" — that visibility is not itself a power. `POST` and `DELETE` are `require_owner`
only; there is no organiser-facing path to either, matching the decision log
(`plan/overview.md`): "Organisers ... Cannot promote or demote organisers, including each
other."

`POST /admin/organisers` targets a `user_id` that must already be a member of some family on
the trip (the same universe `/admin/overview` lists) — appointing someone who has never been
invited onto the trip is not possible, because there is nobody to search for. Appointing an
existing organiser again is idempotent: `200` with the existing row, not a `409`.

`DELETE /admin/organisers/{user_id}` on the trip's `owner_user_id` returns `409
cannot_demote_owner` — the owner is never in `trip_organisers` and is not a valid target.
Demoting a user who is not currently an organiser returns `404`.

Demotion writes only the `trip_organisers` row. It does not touch `family_members.role`,
`sessions`, or anything else — a demoted organiser keeps their session and their family role
and simply stops passing `require_organiser` on their next request. There is no forced
re-login, unlike the reset-password and remove-user flows in Section 4: this is a permission
change, not an access revocation.

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
| `organiser.appointed` | `POST /admin/organisers` succeeds | `{user_id, granted_by}` | **every** client — nav rails re-evaluate whether to show `Admin` |
| `organiser.demoted` | `DELETE /admin/organisers/{id}` succeeds | `{user_id}` | **every** client, and specifically the demoted user's own client, which drops the `Admin` nav entry and any open console tab live |

`stage.changed` is the reserved name from `plan/architecture.md`. `trip.updated`,
`category_settings.updated`, `organiser.appointed` and `organiser.demoted` are **PROPOSED
ADDITIONs** to that list.

The removed or reset user's own socket additionally receives `session.revoked`
(**PROPOSED ADDITION**) via `send_user`, after which the server closes the socket. The client
routes to the login screen with a plain message rather than showing a wall of `401`s. A demoted
organiser does **not** receive `session.revoked` — demotion is a permission change, not an
access revocation, and their session stays valid for everything a plain member can do.

Consumed: nothing. This feature is the source of stage truth, not a consumer of it.

## UI behaviour

Per `plan/design-system.md`. The console is a **sectioned page**, not a modal and not a map
view — its content is configuration, which the reader compares and returns to, and
`design-system.md` reserves overlays for temporary interactions only.

Desktop: a single scrolling column at readable measure with a sticky section index on the
left, inside the standard app shell. This is the one place the 62/38 map split does not apply,
because there is no map dataset here. Mobile: the same sections stacked, with the index
collapsed into a jump menu.

### Trip setup screen (AC-0)

Rendered whenever `auth/me` returns `next_step: "setup_trip"` — the owner's state between
changing the seeded password and naming the trip. A standalone route `/setup/trip`, outside the
app shell: there is no trip to put in the header yet, and every nav destination would be empty.

- Heading and one line of context: "Set up your trip — you can invite families next."
- The same four fields as Section 1 below, in the same order, with the same validation. Name is
  required; timezone is required and pre-filled from the container's `TZ`; the dates are
  optional and labelled "you can decide these later", because a trip in Planning legitimately
  has no dates.
- One `Create trip` action. On success `next_step` becomes `app` and the shell routes to home
  with the trip name in the header.
- Abandoning the screen writes nothing and changes nothing; the next login lands here again,
  because the gate is derived from `setup_complete` rather than from a one-shot redirect.
- Log out is the only other action, and this screen carries it — the nav rail that normally
  holds one is not rendered.
- The screen never appears for anyone else — not even organisers, who inherit `setup_complete`
  the same as everyone but never see `next_step: "setup_trip"`, because that step is keyed to
  the owner's seeded-account password change. A new family head's equivalent is the family
  setup screen in `plan/features/families/` (FM-13); both are reached through foundation's one
  gate, and neither feature reimplements the other's.

### Section 1 — Trip

Form fields for name, start date, end date, timezone, each with all six field states. Explicit
`Save` (AC-2), disabled until something changes. Validation on blur; `end_date` before
`start_date` shows an error beneath the field. While in Planning, empty dates render as a
neutral "not decided yet" placeholder rather than an error, because that is the normal state.

These are the same fields as the setup screen above, rendered by the same form component. The
setup screen is that form with a different frame around it, not a second implementation.

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
confirm dialogs. The row for the owner shows both actions disabled with a tooltip explaining
why — the owner can never be reset or removed from here (see AC-8's out-of-scope note on
transferring ownership).

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

### Section 8 — Organisers (owner only)

Rendered only when `auth/me` reports the caller as the owner; an organiser's console simply
omits this section rather than showing it disabled — there is nothing for an organiser to see
here that isn't already covered by not seeing the card.

- A card/table of current organisers: identity badge, name, family (colour swatch plus name and
  family role if any), "granted by \<name\>", "since \<date\>".
- `Add organiser` opens a search/select over the same member universe as Section 4 (display
  name, username, family), excluding the owner and anyone already an organiser. Selecting a
  person and confirming calls `POST /admin/organisers`.
- Each row's `Remove` action opens a real confirm dialog naming the person and stating plainly
  that they lose every organiser capability immediately, but keep their family role and their
  session — not phrased like the reset/remove actions in Section 4, which do revoke sessions.
- Empty state when there are no organisers yet: "No organisers yet — you're doing this alone,
  or you haven't needed help." with the `Add organiser` action inline.

### Stage-change reception across the app

Every client consumes `stage.changed`. On `end`, the shell shows a persistent archive banner
("This trip has finished — everything is read-only") and mutating controls disappear rather
than failing on press. On a backward correction, controls reappear. The banner is a persistent
element, not a toast, because it is information that must stay visible.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| Neither owner nor organiser opens `/admin` | Access screen in the UI; every endpoint returns `403 forbidden` |
| An organiser opens `/admin/organisers` (or calls its endpoints directly) | Section not rendered client-side; `GET` succeeds (organisers may read the list), `POST`/`DELETE` return `403` |
| Owner abandons trip setup and logs back in | `next_step` is still `setup_trip`; the same screen renders. Nothing was written, so there is no partial trip to reconcile |
| Neither owner nor organiser reaches `/setup/trip` directly | The gate returns their own `next_step`, and the shell renders that instead. `PATCH /admin/trip` returns `403` for a non-organiser; an organiser reaching it directly gets the screen rendered (nothing stops them technically) but their own `next_step` is never `setup_trip`, so the app never routes them there |
| Owner clears the trip name after setup | `422` — name is required by the same validator the setup screen used. `setup_complete` can never go from true back to false |
| Trip seeded with an empty name and `TZ` unset in the container | `timezone` falls back to `UTC` so the field is never blank; `setup_complete` is still false because the name is empty, so the owner is still gated |
| A new family's head finishes family setup before the owner has named the trip | Allowed. The two gates are independent, and the family setup screen shows the trip's name as blank rather than blocking on someone else's task |
| Forward transition without dates | `409 stage_blocked` with `blockers: ["missing_dates"]`; the control was already disabled |
| Illegal transition (e.g. planning → end) | `409 illegal_transition` |
| Owner and an organiser transition at once (or two organisers) | Only one succeeds; the second gets `409 illegal_transition` because the from-stage no longer matches. Implemented as a conditional update on `stage = <expected>` |
| `end_date` before `start_date` | `422 validation_error` on the field |
| Timezone not a valid IANA name | `422 validation_error` |
| Editing trip settings while in End | `409 stage_forbidden` |
| Category mode changed with existing votes | Allowed; votes retained; the confirm named the count. No data is deleted |
| Category row missing (trip predates seeding) | `GET` seeds the missing row with its default on read, so the editor is never partially blank |
| Reset own password via the admin route | `409 cannot_target_self`; the profile page is the route |
| Remove self | `409 cannot_target_self` |
| Remove the last head of a family | `409 last_family_head`, matching `families` |
| Remove a user in the End stage | `409 stage_forbidden` — the archived membership record must not change |
| Reset a password for a user with no family | Allowed; account operations are not membership operations |
| Removed user has the app open | `member.removed` and `session.revoked` on their socket; the client routes to login with a plain message |
| Owner appoints an existing organiser again | `200` with the existing `OrganiserOut`, not a `409` — idempotent |
| Owner attempts to demote themselves | Not reachable through this endpoint — the owner is never a row in `trip_organisers`. `DELETE /admin/organisers/{owner_user_id}` returns `409 cannot_demote_owner` |
| Owner demotes an organiser who heads a family | Succeeds; `family_members.role` is untouched. They keep every family-level power, they lose every trip-level one |
| Organiser calls `POST`/`DELETE /admin/organisers` directly | `403` — `require_owner`, not `require_organiser` |
| Google check pressed twice inside a minute | `429 rate_limited` with `Retry-After`; the button shows the countdown |
| Google check with no server key | Returns immediately with `unchecked` / `no_api_key` for the server APIs and makes no network call |
| Google check partially fails | Each API is classified independently; one failure never masks another's success |
| Google check times out | That API is `unreachable`; the others still report. Per-request timeout of 5 seconds, so the whole press bounds at ~20 seconds |
| `settings` value is corrupt JSON | Treated as "never checked"; the row is overwritten on the next successful check |
| Stats query on a table that does not exist yet | The count reads zero; the console never errors because a later feature is unbuilt |
| Instance name set to empty | `422` — the login screen needs something to show |
| `invite_only` set to false | `422 not_implemented` with the explanatory message |

## Dependencies and hand-offs

- **Depends on `foundation`** for `require_stage`, sessions and revocation, the rate limiter,
  the error envelope, the WebSocket helpers, and the `next_step` onboarding gate (F-13) that
  routes the owner to the trip setup screen.
- **Depends on `families`** for `require_owner` and `require_organiser` (the trip-level
  permission dependencies), the `trip_organisers` table and model, the family and member
  listing shapes, and the `last_family_head` rule which must behave identically in both
  features.
- **Provides to `foundation`** the `setup_complete` predicate that gate reads. Foundation
  defines the field and its precedence; this feature defines when a trip counts as set up.
- **Provides to every voting feature** the `GET /trip/category-settings` read, which decides
  whether the UI renders a 1–10 scale or thumbs. `polls` and `voting-comments` must read it
  rather than assuming a mode.
- **Provides to every feature** the authoritative stage and the `stage.changed` broadcast.
  No other feature may write `trips.stage`.
- **Provides to `holiday-stage`** the transition into and out of `holiday`; that feature adds
  the on-the-day behaviour, not the machine itself.
