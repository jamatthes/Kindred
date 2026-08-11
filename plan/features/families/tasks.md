# families — Tasks

**Milestone M1.** Execute in order; each phase ends with a `Verify:` line that must pass
before the next begins. Read `requirements.md` and `design.md` in this directory first, and
`plan/features/foundation/` for the primitives being reused.

**Prerequisite:** `foundation` is complete. `families` and `family_members` exist as bare
tables from the foundation migration; this feature adds columns, constraints and behaviour.

> **Roles (revised 2026-08-11).** Owner / organiser at trip level, head of family / spouse /
> member at family level — see `requirements.md` > Roles. In every task below, "main admin"
> means **owner or organiser** (`require_organiser`), and "family admin" means **head of
> family**, with a spouse holding the same powers except where the head is the target of the
> action. `require_family_admin` is now `require_family_head_or_spouse`; `require_owner`
> guards organiser management, whose endpoints belong to `admin-console` (FM-17).

## Phase 1 — Migration

- [x] Alembic migration `0002_families`:
  - [x] `families`: add `home_locality` (text null), `geocode_status` (text, default
        `'pending'`, check constraint in `pending|ok|not_found|error`), `geocode_error`
        (text null). Confirm `trip_id`, `name`, `color`, `home_address`, `home_lat`,
        `home_lng`, `home_geocoded_at` already exist from `0001`; add any that do not.
  - [x] `families.color` as `smallint` with a check constraint `between 1 and 8`.
  - [x] `families`: add `location_sharing_allowed` (bool not null default `true`) and
        `member_location_default` (bool not null default `false`).
  - [x] Unique indexes: `(trip_id, lower(name))`, `(trip_id, color)`.
  - [x] `family_members`: unique index on `(user_id)`; add `location_sharing_allowed`
        (bool not null default `true`); `role` in `head|spouse|member` (check-constrained,
        `admin` renamed to `head`) with a **partial unique index on `(family_id) WHERE
        role = 'head'`** — exactly one head per family.
  - [x] `trip_organisers`: new table (trip_id, user_id, granted_by null FK → users
        `ON DELETE SET NULL`, created_at); unique `(trip_id, user_id)`, indexed on
        trip_id. Created here; its endpoints belong to `admin-console` (FM-17).
  - [x] `users`: add `first_name` (text not null) and `last_name` (text not null, default
        `''`), plus `avatar_attachment_id` (uuid null, FK → `attachments`,
        `ON DELETE SET NULL`). Backfill the seeded admin's `first_name` from its
        `display_name` so the not-null constraint holds on an existing install.
  - [x] `invites`: add `trip_id` (uuid, not null, fk), `token_hash` (text, unique, not null)
        replacing plaintext `token`, `revoked_at` (timestamptz null), `used_at`
        (timestamptz null). Keep `family_id` nullable — null means "creates a new family".
  - [x] Index `invites(family_id)` and `invites(expires_at)`.
- [x] Record every one of these as a **PROPOSED ADDITION** in `plan/architecture.md`'s schema
      section in the same commit (docs-first rule in `CLAUDE.md`).

**Verify:** `alembic upgrade head` then `downgrade -1` then `upgrade head` all succeed. In
psql, inserting two families with the same colour on one trip fails; inserting two
`family_members` rows for one user fails; a family created without touching the new columns
has `location_sharing_allowed = true` and `member_location_default = false`.

## Phase 2 — Models

- [x] `models/family.py` — `Family`, `FamilyMember`, `Invite` as SQLAlchemy 2 declarative
      models with typed `Mapped[...]` columns and relationships
      (`Family.members`, `FamilyMember.user`, `Invite.family`).
- [x] A helper `next_free_color(session, trip_id) -> int | None` returning the lowest unused
      slot 1–8, or `None` when all eight are taken.
- [x] A helper `is_invite_usable(invite) -> bool` implementing
      `used_by is null and revoked_at is null and expires_at > now()`.

**Verify:** `pytest server/tests/test_family_models.py` — `next_free_color` returns 1 on an
empty trip, skips taken slots, and returns `None` at eight families; `is_invite_usable`
covers all four falsy cases.

## Phase 3 — Schemas

- [x] `schemas/family.py` — `FamilyOut`, `FamilyDetailOut`, `FamilyCreateIn`,
      `FamilyPatchIn`, `HomeIn`, `MemberOut`, `MemberPatchIn` exactly as sketched in
      `design.md`.
- [x] `schemas/invite.py` — `InviteCreateIn`, `InviteCreatedOut`, `InviteOut`,
      `InvitePreviewOut`, `InviteAcceptIn`.
- [x] Implement the address-visibility rule as a serialiser decision: `FamilyDetailOut`
      includes `home_address`, `home_lat`, `home_lng` and `home_geocoded_at` **only** when the
      caller is a member of that family, the owner, or an organiser. Write it as one function used by
      every route that returns a family, so it cannot be forgotten on a new endpoint.
- [x] `InviteAcceptIn` is `{username, first_name, last_name?, password, password_confirm}`.
      It accepts **no** `family_name` and **no** `display_name`: the family is named on the
      setup screen (Phase 10), and `display_name` is derived server-side as
      `f"{first_name} {last_name}".strip()`.
- [x] Validation: `expires_in_hours` restricted to `24 | 168 | 720`.
- [x] One shared `initials(user)` helper, used by every serialiser that emits `MemberOut` or a
      live-location row — first grapheme of `first_name` plus first grapheme of `last_name`,
      uppercased, falling back to one character when `last_name` is empty. Computing it in two
      places is how a person ends up with two different badges.
- [x] `MemberOut` includes `first_name`, `last_name`, `initials`, `avatar_url`,
      `avatar_thumb_url`, `location_sharing_allowed`, and `location_sharing_enabled` — the
      last **null unless** the caller is that member, their family's head or spouse, the
      owner, or an organiser.

**Verify:** `pytest server/tests/test_family_schemas.py` — the serialiser omits address fields
for a non-member caller and includes them for a member and for the owner;
`InviteAcceptIn` rejects a body carrying `family_name`; `display_name` is derived correctly
including the single-name case; `initials` returns one character when `last_name` is empty and
handles a non-Latin name by grapheme rather than byte; `location_sharing_enabled` is null for a
caller in another family and populated for that member's own head of family.

## Phase 4 — Geocoding service

- [x] `services/google.py` — a `GeocoderProtocol` interface with
      `geocode(address) -> GeocodeResult | None`, a real implementation using
      `GOOGLE_MAPS_SERVER_KEY` with a 5-second timeout, and a `FakeGeocoder` for tests.
- [x] Derive `locality` from address components in order: `postal_town`, `locality`,
      `administrative_area_level_2`.
- [x] Map outcomes to `geocode_status`: a result → `ok`; a well-formed empty result →
      `not_found`; a timeout, transport error or non-200 → `error` with `geocode_error` set;
      a missing key → `error` with `geocode_error = "no_api_key"`, without any network call.
- [x] Wire the fake into the test fixtures so the suite never touches the network.
- [x] Add a module-level comment stating the cost rule: geocode is called only from the
      home-set and home-retry endpoints, never from a read path.

**Verify:** `pytest server/tests/test_geocode.py` with the fake — each of the four outcomes
produces the right status and never raises. Grep the codebase to confirm `geocode(` is called
from exactly two places.

## Phase 5 — Families and members router

- [x] `routers/families.py` with the family routes and member routes from `design.md`.
- [x] Every mutating route declares `Depends(require_stage("planning", "holiday"))` alongside
      its permission dependency.
- [x] `require_pending_family` dependency: admits **only** an authenticated user with no
      `family_members` row whose id appears as `used_by` on a consumed invite with
      `family_id is null`. Everyone else gets `403 forbidden`. Unit-test the four denial cases
      (existing member, removed member, no invite, invite was family-scoped) alongside the
      allow case.
- [x] `POST /families/mine` — the family setup screen's only write. One transaction: create the
      family on the invite's `trip_id` with the lowest free colour, write `family_members` with
      `role='admin'`, set that user's `user_settings.live_location_enabled = true`, geocode the
      home address if supplied. A caller who already has a family gets `409 already_has_family`.
- [x] `PATCH /families/{id}/location-policy` — writes `location_sharing_allowed` and
      `member_location_default`. It must **not** write to any `user_settings` row; assert this
      in a test, because it is the invariant the whole privacy story rests on.
- [x] `PATCH /families/{id}/members/{user_id}` accepts `location_sharing_allowed` alongside
      `role`, and likewise never touches `user_settings`.
- [x] Colour assignment on create: use the requested slot if free, else the next free slot,
      else `409 no_color_slots`.
- [x] `PUT /families/{id}/home`: skip the external call when the address is unchanged and the
      status is already `ok`; otherwise clear the old coordinates, geocode, persist the
      result, and return the detail object for confirmation.
- [x] `DELETE /families/{id}/home`: null `home_address`, lat, lng, `home_locality`,
      `home_geocoded_at`; reset `geocode_status` to `pending`.
- [x] Guard rails, each returning the code named in `design.md`: `name_taken`, `color_taken`,
      `family_not_empty`, `last_family_admin`, `main_admin_protected`.
- [x] Role changes and removals operate through `require_family_head_or_spouse(family_id)`,
      which already admits the owner and organisers for any family. The spouse asymmetry is
      applied per-action against the **target**: a spouse may not remove, demote or switch
      off the head (`403 head_protected`).
- [x] Head transfer: `role: "head"` moves the role in one transaction, demoting the outgoing
      head to `spouse`. A family always has exactly one head, so a bare demotion of the head
      is `409 head_required`.

**Verify:** in `/docs` — create a family as the owner, confirm it gets colour 1; create a
second and confirm colour 2; attempt to set the second to colour 1 and get `409 color_taken`.
Set a home address with the fake geocoder configured to succeed and confirm `home_lat` is
populated. `pytest server/tests/test_families.py` — happy path, permission-denied, and
stage-guard tests for every route, plus a test asserting that **no route in this router writes
`user_settings.live_location_enabled`** except `POST /families/mine` seeding the new family
admin's own row.

## Phase 6 — Invites router and registration

- [x] `routers/invites.py` with the five invite routes.
- [x] Token generation: `secrets.token_urlsafe(32)`; store only the sha256; return the raw
      value exactly once inside `InviteCreatedOut.url`.
- [x] `POST /invites` permission split: non-null `family_id` →
      `require_family_head_or_spouse`; null `family_id` → `require_organiser`.
- [x] `GET /invites/token/{token}` is public and always returns `200` — an unknown, expired,
      used or revoked token yields `valid: false` with a reason and no trip details.
- [x] `POST /invites/token/{token}/accept`:
  - [x] Rate-limited using foundation's limiter, keyed by IP.
  - [x] Refuse when a session is already present (`409 already_member`).
  - [x] Refuse when the trip stage is `end`.
  - [x] Create the user (argon2, `must_change_password=false`) with `display_name` derived
        from the two name fields, and create the `user_settings` row.
  - [x] **`join` mode:** write `family_members` with `role='member'`, and seed
        `user_settings.live_location_enabled` from that family's `member_location_default`.
  - [x] **`create_family` mode:** write **no** family and **no** `family_members` row. The
        family is created later by `POST /families/mine` from the setup screen. Seed
        `live_location_enabled = false`; there is no family to take a default from yet.
  - [x] Mark the invite used with a **conditional update** (`WHERE used_by IS NULL`) inside
        the same transaction; if it affects zero rows, roll back the whole thing and return
        `409 invite_already_used`.
  - [x] Issue a session and CSRF token exactly as login does, then return the user together
        with `next_step` — `app` for `join`, `setup_family` for `create_family`.
- [x] `POST /invites/{id}/revoke` sets `revoked_at`; already-used invites return
      `409 invite_already_used`.

**Verify:** in `/docs` — create a family-scoped invite, preview the token (valid), accept it in
a fresh browser profile, land logged in as a member of that family with `next_step: "app"`.
Accept a new-family invite and confirm the response is `next_step: "setup_family"`, that no
`family_members` row exists, and that `GET /families` then returns `403 not_on_trip`. Preview a
used token and confirm `valid: false, reason: "used"`. `pytest server/tests/test_invites.py`
including a concurrency test that fires two accepts at one token and asserts exactly one
succeeds, and a test that a `join` acceptor into a family with `member_location_default = true`
gets `live_location_enabled = true` while one into a default-false family does not.

## Phase 7 — Profile and avatar endpoints

- [x] `PATCH /api/v1/me` accepting `first_name`, `last_name` and `display_name`, available in
      **all** stages (no `require_stage`), returning the foundation `UserOut`.
- [x] `PUT /api/v1/me/avatar` (multipart) and `DELETE /api/v1/me/avatar`, both stage-exempt for
      the same reason password and theme are.
- [x] Upload pipeline in `services/images.py`, behind an interface so tests do not shell out to
      an image library for every case: sniff the type from magic bytes (never the filename or
      the client's `Content-Type`), reject anything but JPEG/PNG/WebP with `415`, reject over
      8MB with `413`, bound the decode by dimensions and pixel count so a decompression bomb
      gives `422 image_unreadable`.
- [x] Apply EXIF rotation, then **drop all metadata in the re-encode, GPS included**, flatten
      animation to the first frame, centre-crop square, and emit 256px and 64px WebP
      renditions. Do not retain the original.
- [x] Write the `attachments` row with `subject_type='user'` and point
      `users.avatar_attachment_id` at it; replacing an avatar deletes the old row and file in
      the same transaction. Filenames carry a content hash so URLs are immutable.
- [x] Serve avatars through the authenticated attachments route with a long `Cache-Control`
      and an ETag; an unauthenticated request is `401`.

**Verify:** in `/docs` — set the trip stage to `end` via the database, then confirm
`PATCH /me` and the avatar routes still succeed while `PATCH /families/{id}` returns
`409 stage_forbidden`. `pytest server/tests/test_avatar.py` — a JPEG carrying GPS EXIF
round-trips with **no** metadata in either rendition (assert on the decoded output, not on the
absence of an error); a `.jpg` that is actually a ZIP gives `415`; a 9MB file gives `413`; a
crafted decompression bomb gives `422` without exhausting memory; replacing an avatar leaves
exactly one `attachments` row and no orphaned file.

## Phase 8 — WebSocket events

- [x] Emit `family.created`, `family.updated`, `family.deleted`, `member.joined`,
      `member.updated`, `member.removed` from the relevant routes, using foundation's
      `broadcast(trip_id, ...)`.
- [x] `family.updated` carries the coarse `FamilyOut` only — never `home_address` or
      coordinates, because the trip room includes other families.
- [x] `family.updated` also fires on a `location_sharing_allowed` change, and `member.updated`
      on an avatar, name or `location_sharing_allowed` change, so the map reacts without a
      reload.
- [x] `member.updated`'s payload uses the same entitlement rule as the REST serialiser:
      `location_sharing_enabled` is null for recipients not entitled to it. A member's own
      consent state must never reach the whole trip room.
- [x] Send `member.removed` to the removed user's own socket with `send_user` as well as to
      the room.
- [x] Add the six events to `plan/architecture.md`'s WebSocket list as PROPOSED ADDITIONs, in
      the same commit.

**Verify:** `pytest server/tests/test_family_ws.py` — renaming a family delivers
`family.updated` to a connected test client; the payload contains no address field; removing a
member delivers `member.removed` to both the room and that user's own connection.

## Phase 9 — Web: families view

- [x] `web/src/features/families/` — API hooks over foundation's `apiClient`, and a store
      subscribing to the six WebSocket events.
- [x] `FamiliesTable` — tri-state sort, sticky header, full-row click target, tabular figures
      on the member count, colour swatch plus name (never colour alone), density from spacing
      tokens.
- [~] Map layer — one home pin per placed family in `--family-N`, always with a text label;
      an "unplaced families" list beneath the table so they are not invisible.
      **Deferred with the map shell (M2)**: there is no map component in the app yet and
      `plan/architecture.md` reserves the browser Maps SDK for `map-suggestions`. The rule
      that mattered is kept — every family card states its town, "No home set" or "Not
      placed", so an unplaced family is never silently invisible. See the NOTE in
      `design.md` > Families view.
- [x] `FamilyPanel` — desktop right side panel at the 62/38 split; mobile bottom sheet with
      ~40% and ~90% snap points, reusing foundation's `BottomSheet`.
- [x] Home address block with the four states (not set / placed / not found / error), the
      confirm-the-geocode step, and the retry action. The `no_api_key` case links the main
      admin to the admin console.
- [x] `IdentityBadge` in `web/src/design/` (not in this feature's directory — the map,
      presence stack and comments all use it): avatar or `initials`, family-colour ring, sizes
      24/32/40/64, initials on a neutral fill, and initials again when the image fails to load.
      No broken-image state exists.
- [x] Member list with badges, promote / demote / remove, controls rendered only for entitled
      callers. Removing or demoting the head is prevented in the UI with an explanatory
      message, and still refused by the API.
- [x] Family location settings block — the family switch, the new-member default switch, and
      the per-member switches, editable by that family's head or spouse and by the owner and
      organisers, **read-only
      but visible** to members so nobody is silently overridden. Each member row shows its
      effective state using the five strings in `design.md`.
- [x] The family switch uses an undo toast, not a confirm — it is instantly reversible.
- [x] Invite block — create form, copy-once link display with a copy toast and a plain
      "shown only once" line, outstanding-invite list with status chips, revoke with undo.
- [x] The owner's and organisers' `Invite a new family` action, visually separated from per-family
      invites.
- [x] Empty states for no families, and for no outstanding invites.
- [x] Skeletons for the table and panel; spinners for inline saves; optimistic rename and
      recolour with rollback.

**Verify:** in the browser as the owner — create two families, watch the colours differ
on the map, rename one and see it update in a second browser signed in as another user without
a reload. Set a home address and confirm the map preview and confirmation step. Resize to a
phone width and confirm the bottom sheet and ≥ 44px targets. Confirm a member logged into a
different family cannot see the first family's street address anywhere in the network
responses.

## Phase 10 — Web: join, family setup, and profile screens

- [x] `/join/<token>` route outside the app shell: preview first, then the form.
- [x] Invalid-token card with the plain explanation and no trip details.
- [x] Already-logged-in variant with `Log out and continue`.
- [x] End-stage variant explaining the trip has finished, with no form.
- [x] Registration form with all six field states, blur validation, and a per-field
      username-taken error. Fields are first name, last name (marked optional), username,
      password, confirm. **No family-name field and no display-name field.**
- [x] `/setup/family` route outside the app shell, rendered only when foundation's `next_step`
      is `setup_family`: family name (required, `name_taken` shown on the field), optional home
      address marked skippable, the "you will be this family's admin" line, and its own log-out
      action because there is no nav rail.
- [x] Routing reads `next_step` from `auth/me` and nothing else. Do not reimplement the
      precedence in the client — foundation F-13 owns it.
- [x] Profile page: avatar upload/remove with the crop preview and inline error states, first
      and last name inline edits, display name inline edit, all with undo toasts; the member's
      own location-sharing toggle with the settings copy and the "your family is hiding you"
      explanation; password change; theme control; read-only username/family/role block.

**Verify:** in the browser — open a valid family-scoped invite in a private window, register,
and land on the trip as a member of the right family. Open a **new-family** invite, register,
and land on `/setup/family`; close the tab, log in again, and confirm you land there again with
nothing half-created; finish setup and confirm you arrive on home as that family's admin with
your own sharing toggle on. Open a used link and confirm the invalid-token card appears with no
family or trip name. Open an invite while logged in and confirm the log-out path works. Upload
an avatar and confirm the badge updates in a second browser without a reload. Edit a first name
and confirm the undo toast reverts it and the map label follows.

## Phase 11 — Tests

- [x] `test_families.py` — every route: happy path, permission-denied for each role that must
      be refused, and stage-guard rejection in End.
- [x] `test_invites.py` — both invite variants, expiry, revocation, single-use concurrency,
      invalid-token preview leaking nothing, registration creating the correct role.
- [x] `test_family_permissions.py` — a head cannot touch another family; a member cannot
      mutate anything; the owner and organisers can do everything; the owner cannot be removed
      or demoted; an organiser cannot appoint another organiser; and the **spouse asymmetry**:
      a spouse can manage every member of their family but is refused on the head, in every
      direction (remove, demote, promote, visibility switch).
- [x] `test_address_privacy.py` — assert the exact response body for a non-member caller
      contains no `home_address`, `home_lat` or `home_lng` key on any endpoint that returns a
      family, and no `location_sharing_enabled` value on any member of another family.
- [x] `test_family_setup.py` — `require_pending_family` allow and all four denial cases;
      `POST /families/mine` creating exactly one family, one admin membership and one seeded
      `live_location_enabled = true`; a double submit yielding `409 already_has_family` with no
      second family; the eight-slot exhaustion case.
- [x] `test_location_policy.py` — the one that matters most. Assert that **no request body
      reachable by a head, a spouse, an organiser or the owner can set another user's
      `live_location_enabled` to true**: enumerate the routes, call each as a head
      against a member who has consent off, and assert the column is unchanged. Then assert the
      read-time filter: a member is absent from `GET /live-locations` when any one of the three
      permission terms is false, and present only when all three are true and a fresh row
      exists.
- [x] `test_avatar.py` as specified in Phase 7, including the EXIF/GPS stripping assertion.
- [x] Vitest: the families table sort behaviour, the four home-address states, the invite
      copy-once block, permission-gated rendering of the member controls, `IdentityBadge`
      (image, initials, single-name, failed-image), and the family location settings block
      rendering read-only for a member.
- [x] Confirm no test performs a real network call.

**Verify:** `cd server && pytest` green; `cd web && npm test` green. Requirements FM-1 to
FM-15 each map to at least one test or a documented manual step above.

## Hand-off notes

- `distances` consumes `families.home_lat/home_lng`. A null home means "no distances", not an
  error — that feature must degrade, not fail.
- `admin-console` reuses the family and member listings for its overview, and owns account
  deletion and password reset, and the **trip** setup screen (AC-0). This feature owns the
  **family** setup screen. Both are reached through foundation's one `next_step` gate; neither
  reimplements the other.
- Every map feature reads the family colour slot; keep `color` authoritative in the database
  rather than deriving it in the client.
- `holiday-stage` reads the three location-permission columns and the `initials` /
  `avatar_thumb_url` fields, and writes none of them. If a control that changes who appears on
  the map ever needs to exist on the map itself, it belongs here and is linked to from there —
  a permission edited in two places will diverge.

## Revision 2026-08-11 — the owner's family setup, and no memberless families

The user's ruling, executed after the feature had shipped. Requirements and design were updated
first (`docs(families): owner takes the family setup step; no memberless families`), then:

- [x] `is_pending_family` admits the trip's owner with no family, in addition to a founder
      holding a consumed `create_family` invite. The platform-admin carve-out is gone.
- [x] The same predicate keys the invite half on `invites.mode`, not on `family_id is null`,
      so deleting a family cannot convert its members' consumed join invites into licences to
      found one.
- [x] `require_pending_family` takes the active trip, so the dependency and the gate resolve
      ownership identically — otherwise the owner reaches a screen whose submit is refused.
- [x] Gate order asserted as a sequence on a truly fresh install:
      `change_password` → `setup_trip` → `setup_family` → `app`.
- [x] `POST /families` (the bare create) removed — router, `FamilyCreateIn`, the client's
      `familiesApi.create`, the `CreateFamilyForm` dialog, and the `Or add one myself` action
      on the new-family invite card. The families empty state now offers the invite.
- [x] Tests: setup-as-owner creates one family with them as head and their own sharing on; a
      second attempt is refused; the bare create answers `405` for owner, organiser and head;
      an enumeration test asserts no route leaves a family with nobody in it; a removed member
      still resolves to `app` rather than to family setup.

**Verify:** `cd server && pytest` — 485 passed. `cd web && npm run verify` — green.
Seeds, checked end to end against a scratch database: the plain first-run seed gates the owner
`change_password` → `setup_trip` → `setup_family`; a DEMO-seeded database, where the admin is
already head of The Parkers, still lands them at `app`, with zero memberless families. Neither
seed script needed a change.
