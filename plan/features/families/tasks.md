# families — Tasks

**Milestone M1.** Execute in order; each phase ends with a `Verify:` line that must pass
before the next begins. Read `requirements.md` and `design.md` in this directory first, and
`plan/features/foundation/` for the primitives being reused.

**Prerequisite:** `foundation` is complete. `families` and `family_members` exist as bare
tables from the foundation migration; this feature adds columns, constraints and behaviour.

## Phase 1 — Migration

- [ ] Alembic migration `0002_families`:
  - [ ] `families`: add `home_locality` (text null), `geocode_status` (text, default
        `'pending'`, check constraint in `pending|ok|not_found|error`), `geocode_error`
        (text null). Confirm `trip_id`, `name`, `color`, `home_address`, `home_lat`,
        `home_lng`, `home_geocoded_at` already exist from `0001`; add any that do not.
  - [ ] `families.color` as `smallint` with a check constraint `between 1 and 8`.
  - [ ] Unique indexes: `(trip_id, lower(name))`, `(trip_id, color)`.
  - [ ] `family_members`: unique index on `(user_id)`.
  - [ ] `invites`: add `trip_id` (uuid, not null, fk), `token_hash` (text, unique, not null)
        replacing plaintext `token`, `revoked_at` (timestamptz null), `used_at`
        (timestamptz null). Keep `family_id` nullable — null means "creates a new family".
  - [ ] Index `invites(family_id)` and `invites(expires_at)`.
- [ ] Record every one of these as a **PROPOSED ADDITION** in `plan/architecture.md`'s schema
      section in the same commit (docs-first rule in `CLAUDE.md`).

**Verify:** `alembic upgrade head` then `downgrade -1` then `upgrade head` all succeed. In
psql, inserting two families with the same colour on one trip fails; inserting two
`family_members` rows for one user fails.

## Phase 2 — Models

- [ ] `models/family.py` — `Family`, `FamilyMember`, `Invite` as SQLAlchemy 2 declarative
      models with typed `Mapped[...]` columns and relationships
      (`Family.members`, `FamilyMember.user`, `Invite.family`).
- [ ] A helper `next_free_color(session, trip_id) -> int | None` returning the lowest unused
      slot 1–8, or `None` when all eight are taken.
- [ ] A helper `is_invite_usable(invite) -> bool` implementing
      `used_by is null and revoked_at is null and expires_at > now()`.

**Verify:** `pytest server/tests/test_family_models.py` — `next_free_color` returns 1 on an
empty trip, skips taken slots, and returns `None` at eight families; `is_invite_usable`
covers all four falsy cases.

## Phase 3 — Schemas

- [ ] `schemas/family.py` — `FamilyOut`, `FamilyDetailOut`, `FamilyCreateIn`,
      `FamilyPatchIn`, `HomeIn`, `MemberOut`, `MemberPatchIn` exactly as sketched in
      `design.md`.
- [ ] `schemas/invite.py` — `InviteCreateIn`, `InviteCreatedOut`, `InviteOut`,
      `InvitePreviewOut`, `InviteAcceptIn`.
- [ ] Implement the address-visibility rule as a serialiser decision: `FamilyDetailOut`
      includes `home_address`, `home_lat`, `home_lng` and `home_geocoded_at` **only** when the
      caller is a member of that family or the main admin. Write it as one function used by
      every route that returns a family, so it cannot be forgotten on a new endpoint.
- [ ] Validation: `family_name` required when the invite mode is `create_family`, rejected
      otherwise; `expires_in_hours` restricted to `24 | 168 | 720`.

**Verify:** `pytest server/tests/test_family_schemas.py` — the serialiser omits address fields
for a non-member caller and includes them for a member and for the main admin;
`InviteAcceptIn` rejects a `family_name` on a `join` invite and requires one on a
`create_family` invite.

## Phase 4 — Geocoding service

- [ ] `services/google.py` — a `GeocoderProtocol` interface with
      `geocode(address) -> GeocodeResult | None`, a real implementation using
      `GOOGLE_MAPS_SERVER_KEY` with a 5-second timeout, and a `FakeGeocoder` for tests.
- [ ] Derive `locality` from address components in order: `postal_town`, `locality`,
      `administrative_area_level_2`.
- [ ] Map outcomes to `geocode_status`: a result → `ok`; a well-formed empty result →
      `not_found`; a timeout, transport error or non-200 → `error` with `geocode_error` set;
      a missing key → `error` with `geocode_error = "no_api_key"`, without any network call.
- [ ] Wire the fake into the test fixtures so the suite never touches the network.
- [ ] Add a module-level comment stating the cost rule: geocode is called only from the
      home-set and home-retry endpoints, never from a read path.

**Verify:** `pytest server/tests/test_geocode.py` with the fake — each of the four outcomes
produces the right status and never raises. Grep the codebase to confirm `geocode(` is called
from exactly two places.

## Phase 5 — Families and members router

- [ ] `routers/families.py` with the eight family routes and three member routes from
      `design.md`.
- [ ] Every mutating route declares `Depends(require_stage("planning", "holiday"))` alongside
      its permission dependency.
- [ ] Colour assignment on create: use the requested slot if free, else the next free slot,
      else `409 no_color_slots`.
- [ ] `PUT /families/{id}/home`: skip the external call when the address is unchanged and the
      status is already `ok`; otherwise clear the old coordinates, geocode, persist the
      result, and return the detail object for confirmation.
- [ ] `DELETE /families/{id}/home`: null `home_address`, lat, lng, `home_locality`,
      `home_geocoded_at`; reset `geocode_status` to `pending`.
- [ ] Guard rails, each returning the code named in `design.md`: `name_taken`, `color_taken`,
      `family_not_empty`, `last_family_admin`, `main_admin_protected`.
- [ ] Role changes and removals operate through `require_family_admin(family_id)`, which
      already admits the main admin for any family.

**Verify:** in `/docs` — create a family as the main admin, confirm it gets colour 1; create a
second and confirm colour 2; attempt to set the second to colour 1 and get `409 color_taken`.
Set a home address with the fake geocoder configured to succeed and confirm `home_lat` is
populated. `pytest server/tests/test_families.py` — happy path, permission-denied, and
stage-guard tests for every route.

## Phase 6 — Invites router and registration

- [ ] `routers/invites.py` with the five invite routes.
- [ ] Token generation: `secrets.token_urlsafe(32)`; store only the sha256; return the raw
      value exactly once inside `InviteCreatedOut.url`.
- [ ] `POST /invites` permission split: non-null `family_id` → `require_family_admin`;
      null `family_id` → `require_main_admin`.
- [ ] `GET /invites/token/{token}` is public and always returns `200` — an unknown, expired,
      used or revoked token yields `valid: false` with a reason and no trip details.
- [ ] `POST /invites/token/{token}/accept`:
  - [ ] Rate-limited using foundation's limiter, keyed by IP.
  - [ ] Refuse when a session is already present (`409 already_member`).
  - [ ] Refuse when the trip stage is `end`.
  - [ ] Create the user (argon2, `must_change_password=false`), create the `user_settings`
        row, create the family when the mode is `create_family` (assigning the next free
        colour, and the accepting user becomes its `admin`), create the `family_members` row.
  - [ ] Mark the invite used with a **conditional update** (`WHERE used_by IS NULL`) inside
        the same transaction; if it affects zero rows, roll back the whole thing and return
        `409 invite_already_used`.
  - [ ] Issue a session and CSRF token exactly as login does, then return the user.
- [ ] `POST /invites/{id}/revoke` sets `revoked_at`; already-used invites return
      `409 invite_already_used`.

**Verify:** in `/docs` — create a family-scoped invite, preview the token (valid), accept it in
a fresh browser profile, land logged in as a member of that family. Preview the same token
again and confirm `valid: false, reason: "used"`. `pytest server/tests/test_invites.py`
including a concurrency test that fires two accepts at one token and asserts exactly one
succeeds.

## Phase 7 — Profile endpoint

- [ ] `PATCH /api/v1/me` accepting `display_name` only, available in **all** stages
      (no `require_stage`), returning the foundation `UserOut`.
- [ ] Confirm password change and preferences continue to work unchanged from foundation.

**Verify:** in `/docs` — set the trip stage to `end` via the database, then confirm
`PATCH /me` still succeeds while `PATCH /families/{id}` returns `409 stage_forbidden`.

## Phase 8 — WebSocket events

- [ ] Emit `family.created`, `family.updated`, `family.deleted`, `member.joined`,
      `member.updated`, `member.removed` from the relevant routes, using foundation's
      `broadcast(trip_id, ...)`.
- [ ] `family.updated` carries the coarse `FamilyOut` only — never `home_address` or
      coordinates, because the trip room includes other families.
- [ ] Send `member.removed` to the removed user's own socket with `send_user` as well as to
      the room.
- [ ] Add the six events to `plan/architecture.md`'s WebSocket list as PROPOSED ADDITIONs, in
      the same commit.

**Verify:** `pytest server/tests/test_family_ws.py` — renaming a family delivers
`family.updated` to a connected test client; the payload contains no address field; removing a
member delivers `member.removed` to both the room and that user's own connection.

## Phase 9 — Web: families view

- [ ] `web/src/features/families/` — API hooks over foundation's `apiClient`, and a store
      subscribing to the six WebSocket events.
- [ ] `FamiliesTable` — tri-state sort, sticky header, full-row click target, tabular figures
      on the member count, colour swatch plus name (never colour alone), density from spacing
      tokens.
- [ ] Map layer — one home pin per placed family in `--family-N`, always with a text label;
      an "unplaced families" list beneath the table so they are not invisible.
- [ ] `FamilyPanel` — desktop right side panel at the 62/38 split; mobile bottom sheet with
      ~40% and ~90% snap points, reusing foundation's `BottomSheet`.
- [ ] Home address block with the four states (not set / placed / not found / error), the
      confirm-the-geocode step, and the retry action. The `no_api_key` case links the main
      admin to the admin console.
- [ ] Member list with promote / demote / remove, controls rendered only for entitled callers.
      Removal of the last family admin is prevented in the UI with an explanatory message, and
      still refused by the API.
- [ ] Invite block — create form, copy-once link display with a copy toast and a plain
      "shown only once" line, outstanding-invite list with status chips, revoke with undo.
- [ ] The main admin's `Invite a new family` action, visually separated from per-family
      invites.
- [ ] Empty states for no families, and for no outstanding invites.
- [ ] Skeletons for the table and panel; spinners for inline saves; optimistic rename and
      recolour with rollback.

**Verify:** in the browser as the main admin — create two families, watch the colours differ
on the map, rename one and see it update in a second browser signed in as another user without
a reload. Set a home address and confirm the map preview and confirmation step. Resize to a
phone width and confirm the bottom sheet and ≥ 44px targets. Confirm a member logged into a
different family cannot see the first family's street address anywhere in the network
responses.

## Phase 10 — Web: join and profile screens

- [ ] `/join/<token>` route outside the app shell: preview first, then the form.
- [ ] Invalid-token card with the plain explanation and no trip details.
- [ ] Already-logged-in variant with `Log out and continue`.
- [ ] End-stage variant explaining the trip has finished, with no form.
- [ ] Registration form with all six field states, blur validation, per-field username-taken
      error, and the conditional family-name field.
- [ ] Profile page: display name inline edit with undo toast, password change, theme control,
      read-only username/family/role block.

**Verify:** in the browser — open a valid invite in a private window, register, and land on
the trip as a member of the right family. Open the same link again and confirm the
invalid-token card appears with no family or trip name. Open an invite while logged in and
confirm the log-out path works. Edit a display name and confirm the undo toast reverts it.

## Phase 11 — Tests

- [ ] `test_families.py` — every route: happy path, permission-denied for each role that must
      be refused, and stage-guard rejection in End.
- [ ] `test_invites.py` — both invite variants, expiry, revocation, single-use concurrency,
      invalid-token preview leaking nothing, registration creating the correct role.
- [ ] `test_family_permissions.py` — a family admin cannot touch another family; a member
      cannot mutate anything; the main admin can do everything; the main admin cannot be
      removed or demoted.
- [ ] `test_address_privacy.py` — assert the exact response body for a non-member caller
      contains no `home_address`, `home_lat` or `home_lng` key on any endpoint that returns a
      family.
- [ ] Vitest: the families table sort behaviour, the four home-address states, the invite
      copy-once block, and permission-gated rendering of the member controls.
- [ ] Confirm no test performs a real network call.

**Verify:** `cd server && pytest` green; `cd web && npm test` green. Requirements FM-1 to
FM-12 each map to at least one test or a documented manual step above.

## Hand-off notes

- `distances` consumes `families.home_lat/home_lng`. A null home means "no distances", not an
  error — that feature must degrade, not fail.
- `admin-console` reuses the family and member listings for its overview, and owns account
  deletion and password reset. Do not add those here.
- Every map feature reads the family colour slot; keep `color` authoritative in the database
  rather than deriving it in the client.
