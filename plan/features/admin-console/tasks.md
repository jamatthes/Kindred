# admin-console — Tasks

**Milestone M1**, after `families`. Execute in order; each phase ends with a `Verify:` line
that must pass before the next begins. Read `requirements.md` and `design.md` in this
directory first.

**Prerequisites:** `foundation` and `families` complete.

## Phase 1 — Migration

> NOTE (implementation, 2026-08-11): there is no `0003_admin_console`. `CLAUDE.md`'s
> pre-launch migration policy — adopted after this file was written — says there is exactly
> one revision, `0001_schema.py`, and **all schema work edits it in place**, after which the
> dev database is dropped and recreated. The three items below were added there; the
> "upgrade / downgrade / upgrade" verify was run against that single revision. The rest of
> this phase is unchanged.

- [ ] Alembic migration (`0001_schema.py`, edited in place):
  - [ ] `trip_category_settings`: unique index on `(trip_id, category)`; check constraints on
        `category` (`poll|region|accommodation|activity|meal`) and `voting_mode`
        (`score|thumbs`).
  - [ ] New table `trip_stage_transitions` (`id`, `trip_id`, `from_stage`, `to_stage`,
        `direction`, `changed_by`, `created_at`), index on `(trip_id, created_at)`.
  - [ ] `users`: add `last_login_at` (timestamptz null).
- [ ] Backfill: for the existing trip, insert the five `trip_category_settings` rows with the
      defaults from `design.md` (`poll`/`region`/`accommodation` → `score`,
      `activity`/`meal` → `thumbs`).
      *(Implementation: the dev database is recreated rather than backfilled, per the policy
      NOTE above, so seeding at trip creation covers a fresh install. A trip that predates the
      rule is repaired by the self-healing read in Phase 5 — which is the same code path, and
      one fewer thing to keep in step.)*
- [ ] Extend the trip-creation seed so any future trip gets all five rows at creation.
- [ ] Record `trip_stage_transitions`, `users.last_login_at` and the unique index as
      **PROPOSED ADDITION**s in `plan/architecture.md` in the same commit.

**Verify:** `alembic upgrade head`, `downgrade -1`, `upgrade head` all succeed. In psql the
existing trip has exactly five `trip_category_settings` rows; a duplicate `(trip_id, category)`
insert fails.

## Phase 2 — Models and login timestamp

- [ ] `models/trip.py` — add `TripCategorySetting` and `TripStageTransition`.
- [ ] Add `last_login_at` to the `User` model.
- [ ] Update foundation's login route to set `users.last_login_at = now()` on success.
- [ ] A `settings` accessor helper: `get_setting(key, default)` / `set_setting(key, value)`
      handling JSON values, so the Google status blob and the scalar settings share one path.

**Verify:** `pytest server/tests/test_admin_models.py` — a login updates `last_login_at`;
`get_setting` on a missing key returns the default; `set_setting` round-trips a dict.

## Phase 3 — Schemas

- [ ] `schemas/admin.py` — `TripAdminOut`, `TripPatchIn`, `StageChangeIn`,
      `StageTransitionOut`, `CategorySettingOut`, `CategorySettingsPutIn`, `AdminMemberOut`,
      `OverviewOut`, `InstanceSettingsIn/Out`, `GoogleStatusOut`, `StatsOut`, per `design.md`.
- [ ] `TripAdminOut` computes `can_advance_to`, `can_revert_to` and `blockers` server-side —
      the frontend must never derive transition legality itself.
- [ ] Validation: `end_date >= start_date`; `timezone` is a valid IANA name (`zoneinfo`);
      `instance_name` non-empty; `invite_only` accepts only `true`.

**Verify:** `pytest server/tests/test_admin_schemas.py` — `blockers` contains `missing_dates`
for a Planning trip with no dates and is empty once dates are set; an invalid timezone and an
inverted date range both raise `422`.

## Phase 4 — Trip and stage router

- [ ] `routers/admin.py`, every route with `Depends(require_organiser)` (owner OR organiser),
      except the Organisers routes added in Phase 6a, which use `Depends(require_owner)`.
- [ ] `GET`/`PATCH /admin/trip`; the `PATCH` also carries
      `require_stage("planning", "holiday")`.
- [ ] `POST /admin/trip/stage` — **no** `require_stage`, per the carve-out in
      `plan/architecture.md`. Validate the transition against the legal forward and backward
      pairs; enforce `blockers` for forward moves; write a `trip_stage_transitions` row.
- [ ] Apply the stage change as a **conditional update** (`WHERE stage = <expected from>`) so
      two concurrent admins cannot both succeed; zero rows affected →
      `409 illegal_transition`.
- [ ] `GET /admin/trip/stage-history`.

**Verify:** in `/docs` — with dates unset, `POST /admin/trip/stage` to `holiday` returns
`409 stage_blocked` with `blockers: ["missing_dates"]`; set dates and it succeeds; going
straight to `end` from `planning` returns `409 illegal_transition`; reverting from `end` to
`holiday` succeeds. `pytest server/tests/test_admin_stage.py` covers every legal and illegal
pair plus the concurrency case.

## Phase 5 — Category settings

- [ ] `GET`/`PUT /admin/category-settings` (the `PUT` with
      `require_stage("planning", "holiday")`).
- [ ] `GET /trip/category-settings` under `require_member` — the read every voting UI uses.
- [ ] `existing_vote_count` per category: from `poll_scores` for `poll`, from
      `suggestion_votes` for the other four. Return zero when the table has no rows or does
      not yet exist at this milestone.
- [ ] Self-healing read: if a category row is missing, insert it with its default before
      returning, so the editor is never partially blank.

**Verify:** in `/docs` — `GET /trip/category-settings` as an ordinary member returns five rows;
`PUT /admin/category-settings` as that member returns `403`; as the owner or an organiser it
succeeds.
Delete one row directly in psql, re-read, and confirm it is recreated with its default.

## Phase 6 — Overview, reset password, remove user

- [ ] `GET /admin/overview` with an optional `q` filter across display name, username and
      family name.
- [ ] `POST /admin/users/{id}/reset-password` — generate a 4-word hyphenated password from a
      bundled wordlist, hash it with argon2, set `must_change_password = true`, revoke all of
      that user's sessions, return the plaintext exactly once. Never log it.
- [ ] `DELETE /admin/users/{id}` with `require_stage("planning", "holiday")` — delete the
      `family_members` row, revoke sessions, keep the `users` row and all authored content.
- [ ] Guards: `cannot_target_self` on both routes; `last_family_head` on removal, reusing the
      same check `families` uses so the two cannot diverge.
- [ ] Send `session.revoked` to the target's own socket, then close it.

**Verify:** in `/docs` — reset a member's password, confirm the response carries a readable
temporary password, then confirm that member's existing session returns `401` and that logging
in with the temporary password lands on the forced-change screen. Remove a member and confirm
in psql that their `users` row and any authored rows still exist while `family_members` is
gone. `pytest server/tests/test_admin_users.py`.

## Phase 6a — Organiser management (AC-13)

- [ ] `GET /admin/organisers` — `require_organiser`, lists `trip_organisers` joined to
      `users`/`family_members` for `OrganiserOut` per `design.md`.
- [ ] `POST /admin/organisers` — `require_owner`, `{user_id}`, inserts a `trip_organisers` row
      with `granted_by = current_user`. Idempotent: appointing an existing organiser again
      returns `200` with the existing row, not a new one or a `409`.
- [ ] `DELETE /admin/organisers/{user_id}` — `require_owner`. Returns `409
      cannot_demote_owner` if `user_id == trips.owner_user_id`; `404` if the user is not
      currently an organiser; otherwise deletes the row. Does **not** touch
      `family_members.role` and does **not** revoke sessions or emit `session.revoked` —
      demotion is a permission change, not an access revocation.
- [ ] Emit `organiser.appointed` / `organiser.demoted` to the whole trip room on each mutation
      (**PROPOSED ADDITIONs**, add to `plan/architecture.md`'s event list in the same commit as
      Phase 8).

**Verify:** in `/docs` — as an organiser, `GET /admin/organisers` succeeds and `POST`/`DELETE`
both return `403`. As the owner, appoint a member and confirm they appear in the list with the
owner's name as `granted_by`; appoint them again and confirm `200` with no duplicate row in
psql. Demote them and confirm `family_members.role` is unchanged and their existing session
still passes `require_member` on an ordinary route. Attempt `DELETE
/admin/organisers/{owner_user_id}` and confirm `409 cannot_demote_owner`.
`pytest server/tests/test_admin_organisers.py`.

## Phase 7 — Instance settings, Google status, stats

- [ ] `GET`/`PATCH /admin/settings` — no stage guard. `invite_only: false` → `422
      not_implemented`.
- [ ] Extend `services/google.py` with `probe() -> dict[str, ProbeResult]` covering Geocoding,
      Distance Matrix, Directions and Places, each with a 5-second timeout, classified per the
      table in `design.md`. Add a fake for tests.
- [ ] `GET /admin/google-status` — reads the stored `settings` blob, makes **no** network
      call.
- [ ] `POST /admin/google-status/check` — rate-limited to 1/min via foundation's limiter,
      runs the probe, stores the blob with `checked_at` and `checked_by`, returns it.
- [ ] Maps JS is reported as configured / not configured only, with no probe.
- [ ] `GET /admin/stats` — one trip-scoped count per metric; hardcode zero for tables that do
      not exist at this milestone, with a comment naming the feature that will supply each.

**Verify:** in `/docs` with no `GOOGLE_MAPS_SERVER_KEY` set — `POST .../check` returns
`unchecked` / `no_api_key` for the server APIs and makes no outbound request (confirm with
container logs or a network capture). Press it twice inside a minute and get `429`.
`GET /admin/stats` returns a complete object with zeroes and no error.
`pytest server/tests/test_google_status.py` with the fake covers `ok`, `denied`, `quota`,
`unreachable` and `no_api_key`.

## Phase 8 — WebSocket events

- [ ] Emit `stage.changed` to the whole trip room on every transition, forward or backward.
- [ ] Emit `trip.updated` on name/date/timezone changes and
      `category_settings.updated` on voting-mode changes.
- [ ] Emit `member.removed` on user removal, reusing the exact payload shape from `families`
      so one client handler serves both.
- [ ] Emit `session.revoked` to the target user's own socket on reset and removal, then close
      it.
- [ ] Emit `organiser.appointed` / `organiser.demoted` to the whole trip room (see Phase 6a) —
      **no** `session.revoked` on demotion.
- [ ] Add `trip.updated`, `category_settings.updated`, `session.revoked`,
      `organiser.appointed` and `organiser.demoted` to `plan/architecture.md`'s event list as
      PROPOSED ADDITIONs.

**Verify:** `pytest server/tests/test_admin_ws.py` — a transition delivers `stage.changed` to a
connected member's socket; a password reset delivers `session.revoked` to that user only and
closes their connection.

## Phase 9 — Web: console page

- [ ] `web/src/features/admin/` with the section layout from `design.md`: single readable
      column, sticky section index on desktop, collapsed jump menu on mobile.
- [ ] Nav rail / tab bar entry rendered for the owner and for organisers; a direct-URL access
      screen for everyone else.
- [ ] **Trip** section — the four fields with all six states, explicit `Save` disabled until
      dirty, inline date validation, the "not decided yet" placeholder while in Planning.
- [ ] `/setup/trip` route (AC-0) outside the app shell, rendered only when foundation's
      `next_step` is `setup_trip`: the **same form component** as the Trip section with a
      different frame, a `Create trip` action, and its own log-out action because there is no
      nav rail. Two implementations of this form is two places for validation to drift.
- [ ] `TripAdminOut.setup_complete` (`name` non-empty and `timezone` set) is computed
      server-side and is the same predicate foundation's gate reads — exported from one place,
      not reimplemented in the gate.
- [ ] Seed the trip with `name = ''` and `timezone` from the container's `TZ` (falling back to
      `UTC`), so a fresh install gates the owner instead of shipping a placeholder name into
      the app header.

**Verify (AC-0):** on a fresh stack, log in as `admin`/`admin`, change the password, and confirm
you land on `/setup/trip` rather than home. Close the tab, log in again, and confirm you land
there again with nothing half-written. Submit a name and confirm you arrive on home with that
name in the header and `next_step: "app"`. Confirm someone who is neither owner nor organiser
hitting `/setup/trip` directly renders their own `next_step` screen and that `PATCH
/admin/trip` returns `403` for them.
- [ ] **Stage** section — current stage with its description, the forward primary action, the
      visually separated backward correction, disabled state with the blocker reason in words,
      and the stage-history table.
- [ ] Confirm dialogs with the exact consequence copy from `design.md` and action-labelled
      buttons ("Start the holiday", "Freeze the trip") — never a bare "OK".
- [ ] **Voting modes** section — five rows, segmented control, `Save`, and the
      existing-votes confirm naming the count.
- [ ] **Families and members** section — both tables using the shared table pattern (tri-state
      sort, sticky header and first column, tabular right-aligned numerics, full-row targets),
      one search box filtering both, status chips as icon plus text.
- [ ] Row actions with real confirms; both actions disabled with an explanatory tooltip on the
      owner's own row.
- [ ] Reset-password result as a copy-once block with a copy toast and the "shown only once"
      line.
- [ ] **Instance** section — name field, registration radio group with the disabled options
      visible and annotated.
- [ ] **Google APIs** section — the table, the `Run check` button with its plain caption and
      the one-minute countdown, status chips as icon plus word, inline hints on failures, and
      the never-checked empty state.
- [ ] **Stats** section — a grid of labelled tabular numbers, zeroes shown, no chart.
- [ ] **Organisers** section (AC-13) — rendered for the owner only (organisers see every other
      section but not this one); the list, the `Add organiser` search/select over the member
      universe, and the `Remove` confirm naming the effect without session-revocation language.
- [ ] Skeletons for each section while loading; spinners for inline saves.

**Verify:** in the browser as the owner — walk every section including Organisers, save each,
and confirm the values persist across a reload. As an organiser, confirm every section but
Organisers renders. Confirm a plain member signed in elsewhere cannot see the `Admin` entry and
gets the access screen at the URL. Press `Run check` and confirm the countdown. Appoint a
member as an organiser from the Organisers section and confirm their `Admin` nav entry appears
live in a second open browser without a reload.

## Phase 10 — App-wide stage reception

- [ ] Subscribe the app shell to `stage.changed`; update the cached trip and re-render.
- [ ] Persistent archive banner in the End stage ("This trip has finished — everything is
      read-only"), not a toast.
- [ ] A shared `useStage()` helper exposing `canMutate`, used by feature UIs to hide mutating
      controls rather than letting them fail on press. The backend guard remains the
      enforcement; this is presentation only.
- [ ] Handle `session.revoked`: close the socket, clear local state, route to login with a
      plain message.

**Verify:** with two browsers open — advance the stage in one and confirm the other shows the
banner and loses its mutating controls within a second, without a reload. Revert the stage and
confirm the controls return.

## Phase 11 — Tests

- [ ] `test_admin_permissions.py` — every route in this feature returns `403` for a head/spouse
      and for a member; every route except the Organisers routes succeeds for an organiser; the
      Organisers `GET` succeeds for an organiser but its `POST`/`DELETE` return `403` for one.
- [ ] `test_admin_stage.py` — all legal and illegal transitions, blockers, the concurrency
      conditional update, history rows written with the correct direction, both by the owner
      and by an organiser.
- [ ] `test_admin_stage_freeze.py` — with the trip in `end`, assert a representative mutating
      route from **each** completed feature returns `409 stage_forbidden`, and that
      `POST /admin/trip/stage` still succeeds. Extend this test as each later feature lands —
      it is the guard that keeps the freeze real.
- [ ] `test_admin_users.py` — reset (session revocation, forced change, self-target refusal,
      plaintext returned once), removal (content retained, `last_family_head` refusal,
      End-stage refusal).
- [ ] `test_admin_organisers.py` — appointment (idempotent re-appoint), demotion (family role
      untouched, session untouched, no `session.revoked`), owner cannot be demoted, non-owner
      organiser gets `403` on `POST`/`DELETE` but `200` on `GET`, demoted organiser immediately
      fails `require_organiser` on the next request.
- [ ] `test_category_settings.py` — member read allowed, member write refused, self-healing
      read, `existing_vote_count`.
- [ ] `test_google_status.py` — all five classifications with the fake, the rate limit, and an
      assertion that `GET /admin/google-status` performs no call.
- [ ] Vitest: the stage confirm dialogs render the right consequence copy, the disabled
      forward action shows its blocker, the console is not rendered for a non-owner/non-organiser,
      the Organisers section is not rendered for an organiser, and the Google status table
      renders each status with text and not colour alone.

**Verify:** `cd server && pytest` green; `cd web && npm test` green. Requirements AC-1 to
AC-13 each map to at least one test or a documented manual step above.

## Hand-off notes

- No other feature may write `trips.stage`. If one needs a transition, it calls this router.
- Every voting UI must read `GET /trip/category-settings` rather than assuming a mode; the
  `poll` category governs all polls (see the NOTE on AC-5 in `requirements.md`).
- `test_admin_stage_freeze.py` is the shared regression guard for the End-stage freeze. Every
  feature that adds a mutating route adds a line to it.
- Stats counts are stubbed at zero for unbuilt features; each later feature replaces its own
  stub as part of its tasks.
- `require_owner` and `require_organiser` are `families`' dependencies (see that feature's
  tasks); this feature is their first and primary consumer for trip-level gating. If those
  dependency names land differently than assumed here, update Phase 4 onward and the guard
  columns in `design.md` in the same commit.
