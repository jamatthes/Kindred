# Kindred — Architecture

## System shape

```
[Family browsers / phones (PWA)]
        │  HTTPS (Cloudflare proxy — IPv4+IPv6 edge → IPv6 home server origin)
        ▼
[Caddy reverse proxy]  ── static web build (React PWA)
        │
        ├── /api/**  → [FastAPI]  ── REST + Pydantic schemas, OpenAPI at /docs
        ├── /ws      → [FastAPI]  ── one WebSocket: votes, pins, notifications, live locations
        ▼
[PostgreSQL]
        ▲
[FastAPI background tasks] → Google APIs (Distance Matrix, Geocoding, Directions, Places)
                           → NOAA api.weather.gov / Open-Meteo (weather)
                           → Web Push (VAPID) to subscribed devices
```

- **Everything external is called server-side and cached in Postgres** except the Google Maps JS map itself and Places Autocomplete/Details in the create-suggestion flow (browser SDK requirement).
- One WebSocket channel per authenticated session; server pushes typed events, namespaced by domain (`poll.vote.updated`, `suggestion.vote.updated`, `suggestion.created`, `notification.new`, `location.updated`, `stage.changed`, `presence.updated`). Frontend applies optimistic UI for own actions.
- **PROPOSED ADDITIONs (accepted, `polls`):** `poll.created`, `poll.updated`, `poll.deleted`, `poll.closed`, `poll.decided`, `poll_option.created`, `poll_option.deleted`, `comment.created`. `poll.vote.updated` and `notification.new` were already reserved above. **`poll.vote.updated` carries the whole recomputed `PollResultsOut`, not a delta** — recomputation is one cheap query at this scale, and shipping the entire object removes any possibility of the matrix, the charts and the map drifting apart from partially applied deltas. `notification.new` goes per recipient via `send_user`; everything else is a trip-room broadcast. Rationale in `plan/features/polls/design.md` > WebSocket events.
- **PROPOSED ADDITIONs (accepted, `families`):** `family.created`, `family.updated`, `family.deleted`, `member.joined`, `member.updated`, `member.removed`. `family.updated` carries the coarse `FamilyOut` only and `member.updated` carries a `MemberOut` whose `location_sharing_enabled` is null — both are broadcast to the whole trip room, which includes other families, so neither may carry a full address or a consent state. `member.removed` also goes to the removed user's own socket via `send_user`, so their client can refetch `auth/me` and show "you are no longer on this trip" rather than erroring through a screen it can no longer load. Rationale in `plan/features/families/design.md` > WebSocket events.
- **PROPOSED ADDITIONs (accepted, `admin-console`):** `trip.updated`, `category_settings.updated`, `organiser.appointed`, `organiser.demoted`, and `session.revoked`. The first four go to the whole trip room: a name change belongs in every header, a voting-mode change in every voting UI, and an organiser appointment or demotion changes whether a client renders the `Admin` entry at all — the demoted user's own client drops it live. `session.revoked` is the exception and goes only to the target's own socket via `send_user`, immediately before the server closes it, so a password reset or a removal ends as a plain "you have been signed out" rather than a wall of `401`s. Demotion deliberately emits **no** `session.revoked`: it is a permission change, not an access revocation. Rationale in `plan/features/admin-console/design.md` > WebSocket events.
- **PROPOSED ADDITIONs (accepted, `map-suggestions`):** `suggestion.updated`, `suggestion.moved`, `suggestion.status_changed`, `suggestion.deleted`. `suggestion.created` was already reserved above. All five are trip-room broadcasts carrying the whole `SuggestionOut` (except `.moved`, which carries `id, lat, lng, geometry_geojson`, and `.deleted`, which carries `id`) — the same "ship the object, not a delta" reasoning as `poll.vote.updated`: the map, the list and the side panel must not be able to drift apart from partially applied deltas. `suggestion.moved` is emitted **in addition to** `suggestion.updated`, and only past the 25 m epsilon, so a client that only redraws pins can subscribe to the cheap one. Rationale in `plan/features/map-suggestions/design.md` > WebSocket events.
- **PROPOSED ADDITIONs (accepted, `voting-comments`):** `suggestion.vote.updated` and `comment.updated` / `comment.deleted`. `comment.created` and `notification.new` were already reserved. `suggestion.vote.updated` carries the whole recomputed tally **minus `my_vote`** — that field is per recipient, and putting it on a room-wide frame would let one client overwrite another's local state with a vote that is not theirs; clients merge the broadcast tally with the vote they know they cast. An undo-delete deliberately emits `comment.created` rather than a sixth event: a restore is indistinguishable from a create for a consumer reconciling by `id`. `notification.new` for a mention goes to that person alone via `send_user`, never to the room, because broadcasting it would tell everybody who was pinged about what. Rationale in `plan/features/voting-comments/design.md` > WebSocket events.
- Almost every event fans out to the whole trip room unfiltered. **`location.updated` is the exception**: its audience is evaluated per recipient against the visibility rule below, because broadcasting a coordinate to a client that must not see it and relying on a client-side filter would make that filter advisory. Any future event carrying data some members may not see needs the same treatment, and needs to say so where it is defined.
- **Presence** is ephemeral: the socket registry knows which users have live sessions, broadcasts `presence.updated {user_id, online}` on connect/disconnect (with a short debounce so refreshes don't flap), and answers a REST snapshot for initial render. No table — presence is never persisted. It drives the top bar's family avatar stack (see `plan/design-system.md`).

## Repo layout (monorepo)

```
Kindred/
├── CLAUDE.md            # agent onboarding — read first
├── plan/                # this documentation (docs-first workflow)
├── server/              # FastAPI app
│   ├── app/
│   │   ├── main.py, deps.py, ws.py
│   │   ├── models/      # SQLAlchemy models
│   │   ├── schemas/     # Pydantic request/response
│   │   ├── routers/     # one router per feature
│   │   ├── services/    # google.py, weather.py, push.py, distances.py
│   │   └── core/        # config, security, sessions
│   ├── alembic/         # migrations — ONE file pre-launch (see below)
│   └── tests/
├── web/                 # React + Vite PWA
│   ├── Caddyfile        # serves dist/ and proxies /api + /ws; COPYed into the web image
│   └── src/
│       ├── design/      # tokens.css, themes, primitives
│       ├── charts/      # own chart widget library
│       ├── features/    # one dir per feature (mirrors plan/features)
│       ├── map/         # Google Maps wrapper components
│       └── app/         # shell, routing, ws client, api client
├── deploy/
│   ├── docker-compose.yml   # web (caddy+static), api, postgres
│   └── .env.example         # DB creds, GOOGLE_MAPS_API_KEY, VAPID keys, SECRET_KEY
├── data/                # gitignored; bind-mounted container data, visible to the operator
│   ├── postgres/        # the Postgres data directory (PGDATA=.../pgdata inside it)
│   └── attachments/     # uploaded photos and profile pictures
└── legacy notes: reference app lives at E:\GitRepos\palantir-for-family-trips (NOT copied here)
```

## Database schema (multi-trip-ready; v1 UI uses one trip)

All tables `id` (uuid pk), `created_at`, `updated_at` unless noted. FKs implied by names.

### Identity
- **users** — username, password_hash (argon2), first_name, last_name (may be empty), display_name (seeded "first last", separately editable), avatar_attachment_id (nullable), must_change_password (bool, seeds true for `admin`), theme_pref (`light`/`dark`/`system`), locale, is_platform_admin (bool)
- **families** — trip_id, name, color (token slot, used for map pins/labels), home_address (text), home_lat/home_lng (nullable until geocoded), home_geocoded_at, home_locality (nullable coarse label), geocode_status (`pending`/`ok`/`not_found`/`error`, check-constrained, default `pending`), geocode_error (nullable), location_sharing_allowed (bool default true), member_location_default (bool default false). `color` is `smallint` **NOT NULL**, check-constrained `between 1 and 8`. Unique on `(trip_id, lower(name))` and on `(trip_id, color)`. *families*
- **family_members** — family_id, user_id, role (`head`/`spouse`/`member`, check-constrained), location_sharing_allowed (bool default true). **Unique on `user_id`**: a user belongs to exactly one family. One `head` per family; any number of `spouse`. A spouse has the head's powers over the family except over the head themselves (see `plan/features/families/`). *families*
- **trip_organisers** — trip_id, user_id, granted_by (nullable, FK → users `ON DELETE SET NULL`), created_at. **Unique on (trip_id, user_id).** No `updated_at` — the row's existence *is* the grant, so there is nothing to mutate; revoking is a delete. Appointed and removed **only by the trip owner** (`trips.owner_user_id`). Indexed on trip_id. The table is created by `families` because its permission dependencies need it; the endpoints and UI that manage it belong to `admin-console`. *families*
- **invites** — trip_id, **mode** (`join`/`create_family`, check-constrained, default `join`), family_id (nullable), token_hash (sha256; the raw token is shown once at creation and never stored), expires_at, created_by, used_by (nullable), used_at (nullable), revoked_at (nullable). Usable when `used_by is null and revoked_at is null and expires_at > now()`. `family_id` is `ON DELETE SET NULL`, so a deleted family leaves the invite reportable as `invite_family_missing` rather than vanishing with it. Indexed on family_id, trip_id and expires_at; token_hash unique. *families*

  > `mode` replaces the original rule "family_id nullable = invite creates a new family", which could not coexist with `ON DELETE SET NULL`: deleting a family silently converted its outstanding join invites into family-founding ones, so accepting one would create an account and send the visitor to a family setup screen they were never invited to. With `mode` stated explicitly, `family_id is null` means one thing only — `mode = 'join'` plus a null family is the `invite_family_missing` condition, and `mode = 'create_family'` is FM-6. Caught by `tests/test_invites.py::test_accepting_into_a_deleted_family_is_a_distinct_failure`.
- **sessions** — user_id, token_hash (sha256 of the opaque cookie value; the raw value is never stored), csrf_token, expires_at, revoked_at (nullable), user_agent (nullable), ip (inet, nullable), last_seen_at, created_at. No `updated_at` — `last_seen_at` is the mutable column, touched at most once a minute. Valid when `revoked_at is null and expires_at > now()`. Indexed on user_id and expires_at; token_hash unique. Expired rows removed by a lazy sweep on login, not a scheduler. *foundation*
- **login_attempts** — username (lowercased; recorded even when no such user exists), ip (inet, nullable), succeeded, created_at. No `updated_at` — rows are append-only. Indexed on created_at and on (username, created_at) / (ip, created_at). A login is refused when either the username or the IP has ≥ `RATE_LIMIT_LOGIN_PER_MINUTE` failures in the trailing 60 seconds; a success clears that username's recent failures; rows older than an hour are swept lazily on login. *foundation*

### Trip + configuration
- **trips** — name, stage (`planning`/`holiday`/`end`), start_date/end_date (nullable in planning), owner_user_id (main admin), timezone
- **trip_category_settings** — trip_id, category (`poll`/`region`/`accommodation`/`activity`/`meal`), voting_mode (`score`/`thumbs`)
- **settings** — key/value platform config (singleton rows: instance name, registration open, etc.)

### Deciding
- **polls** — trip_id, title, description, kind (`score_matrix`/`options`, check-constrained, **immutable after creation**), status (`open`/`closed`, check-constrained), created_by, allow_member_options (bool), **decision_option_id** (nullable, FK → poll_options `ON DELETE SET NULL`), **decided_by**, **decided_at**, **closed_at**, **closed_by**, **last_nudge_at**. Indexed on trip_id. *polls*
- **poll_options** — poll_id, label, created_by, lat/lng + place_id (nullable — geographic options become map overlays), sort, **suggestion_id** (nullable uuid, **no FK constraint at M2** — `suggestions` does not exist until `map-suggestions`, which adds it). Indexed on (poll_id, sort). *polls*
- **poll_scores** — poll_id, option_id, user_id, score (smallint 0–10) **or** thumb (`up`/`down`); unique (option_id, user_id). Both columns nullable with a check that at least one is set, plus range and enum checks. Two columns rather than one overloaded value **on purpose**: a score and a thumb for the same (option, user) coexist in one row, which is what makes "switching the voting mode deletes nothing" (polls PL-4) true — the active mode decides which is read. Indexed on poll_id and user_id. *polls*
- **suggestions** — trip_id, type (`region`/`accommodation`/`activity`/`meal`), title, notes, status (`proposed`/`shortlisted`/`approved`/`scheduled`/`rejected`), created_by, lat/lng (point types), geometry_geojson (regions: circle/polygon), place_id (nullable), place_snapshot_json (user-authored fields only — name/address as entered; Google details are re-fetched live, per ToS), external_url (Airbnb links etc.). **Implemented** at M3: `type` and `status` check-constrained; `lat`/`lng` **NOT NULL** including for regions, which store their centroid there so a region sorts, selects and takes a distance exactly like a pin; a check constraint `(type = 'region') = (geometry_geojson IS NOT NULL)`, so geometry-iff-region is a database fact rather than a service-layer promise; indexes on `(trip_id, status)`, `(trip_id, type)` and `place_id` (non-unique — an accommodation and a meal at the same hotel legitimately share one). `created_by` is `ON DELETE SET NULL`: a proposal the group already voted on survives its author's account. **Grouping is derived, never stored** — an activity or meal at an accommodation is nested at query time, so moving a pin re-groups with no migration. *map-suggestions*
- **suggestion_votes** — suggestion_id, user_id, score (0–10) or thumb, unique (suggestion_id, user_id). **Implemented** at M3: the unique constraint is what makes one-vote-per-user structural rather than a race-prone application check — voting is an `INSERT ... ON CONFLICT DO UPDATE` onto it. Check-constrained `(score IS NULL) <> (thumb IS NULL)` — *exactly* one, unlike `poll_scores`' weaker "at least one", because a suggestion vote is one answer at a time and a mode change is a **display** conversion over what is stored rather than a second stored value. Both FKs cascade. Indexed on suggestion_id and user_id. *voting-comments*
- **comments** — polymorphic: subject_type (`suggestion`/`poll`/`itinerary_item`, check-constrained), subject_id, author_id (nullable, `ON DELETE SET NULL` — a removed account leaves its discussion attributed to nobody rather than deleting it), body (with @mention markup), edited_at (nullable). Indexed on (subject_type, subject_id). **Carries no FK to its subject** — that is the cost of one thread implementation serving three subjects, so deleting a poll deletes its comments in the service layer, in the same transaction. Created by *polls*

### Agreed plan
- **itinerary_items** — trip_id, suggestion_id (nullable — admin can add directly), day (date), start_time/end_time (nullable), title override, confirmed_by, sort
- **route_cache** — trip_id, from_lat/lng, to_lat/lng, polyline, duration_s, distance_m, provider (`google`), computed_at; recomputed only when itinerary changes
- **distance_cache** — family_id, suggestion_id, duration_s, distance_m, mode (`driving`), computed_at; recomputed only when pin moves; unique (family_id, suggestion_id)
- **weather_cache** — lat/lng (rounded grid key), date, payload_json, fetched_at (TTL ~1h)

### On the day
- **checkins** — trip_id, user_id, lat/lng, accuracy_m, note (nullable), created_at
- **live_locations** — user_id (unique), trip_id, lat/lng, accuracy_m, updated_at; upserted by foreground watchPosition; row deleted when sharing toggled off
- **user_settings** — user_id, live_location_enabled (bool default false), push_enabled (bool)

### Platform
- **notifications** — recipient_user_id, type, payload_json (deep-link target), read_at (nullable). Indexed on (recipient_user_id, created_at), matching the bell's "my unread, newest first". Created by *polls*, which writes `poll.nudge` rows from M2 onward even though the *notifications* feature (M6) builds the UI that reads them — deferring the write would mean the nudge silently did nothing.
- **push_subscriptions** — user_id, endpoint (unique), p256dh, auth, user_agent, last_used_at, failure_count, created_at
- **attachments** — subject_type/subject_id, uploader_id, file path (local volume), mime, width/height; used for photos on suggestions/check-ins/archive, and for profile pictures (`subject_type = 'user'`, referenced back from `users.avatar_attachment_id`). All uploads are re-encoded server-side and **stripped of EXIF, GPS included** — a location-privacy product must not republish coordinates hidden in a photo. Also carries `thumb_path` (nullable — avatars emit two renditions, 256px and 64px, and `MemberOut` exposes both) and `byte_size` (what was written after re-encoding, which is not the size of the upload). *families*

### Approved additions (proposed in feature design docs, accepted 2026-08-10)

These originated as PROPOSED ADDITION items in `plan/features/*/design.md` and are approved;
the feature docs carry the rationale.

- ~~**sessions** (new table) — server-side sessions (revocation on password reset). *foundation*~~ — **implemented**; specified in full under Identity above.
- ~~**login_attempts** (new table) — login rate limiting. *foundation*~~ — **implemented**; specified in full under Identity above.
- ~~**trip_stage_transitions** (new table) — audit of who changed stage and when. *admin-console*~~ — **implemented**: `trip_id`, `from_stage`, `to_stage`, `direction` (`forward`/`backward`, stored rather than derived), `changed_by` (FK users, `ON DELETE SET NULL` — removing an account must not delete the record that it moved the stage), `created_at`; index on `(trip_id, created_at)`. Append-only; the only audit trail in v1.
- **notification_preferences** (new table) — user_id, category, enabled; absent row = enabled. *notifications*
- ~~**users.last_login_at** — admin console visibility. *admin-console*~~ — **implemented**: timestamptz null, written by foundation's login route. `created_at` cannot answer "has this person ever got in?" — an invited account that was never used looks identical to one used daily.
- **families.home_locality, geocode_status, geocode_error** — locality shown to other families without leaking the street address; geocode failure states. *families*
- **family_members** — unique index on user_id (a user belongs to one family). *families*
- **family_members.role gains `spouse`, and `admin` is renamed `head`** — a household usually has two adults, and making one of them a plain member misdescribes the family the software is modelling. *families* (added 2026-08-11)
- **trip_organisers** (new table) — the owner delegates cross-family powers without delegating the power to delegate. *families* creates it and honours it; *admin-console* owns the endpoints (added 2026-08-11)
- **invites.trip_id, token_hash, revoked_at, used_at** — hashed single-use invite tokens. *families*
- **users.first_name, users.last_name** — collected at registration; `display_name` seeded to "first last" and still separately editable. Needed because the map badge is initials and its hover label is a full name, neither of which can be derived reliably from a single free-text field. *families*
- **users.avatar_attachment_id** (nullable, FK → attachments, ON DELETE SET NULL) — profile picture; the image itself is an `attachments` row with `subject_type = 'user'`. *families*
- **families.location_sharing_allowed** (default true), **families.member_location_default** (default false) — the family admin's map-visibility switch and the value new members' sharing toggle is seeded with. *families*
- **family_members.location_sharing_allowed** (default true) — the family admin's per-member map-visibility switch. *families*

> **Location visibility is the conjunction of four independent facts**, three of them
> permissions and one of them consent: `families.location_sharing_allowed`,
> `family_members.location_sharing_allowed`, `user_settings.live_location_enabled`, and a fresh
> `live_locations` row. The first two are written only by a family admin; the third only by the
> member themselves; the fourth only by that member's browser. No API accepts a request that
> sets another user's consent — admins can remove a marker, never create one. The single point
> where an admin's decision reaches a member's own setting is the one-time seed from
> `member_location_default` at join, which is still gated by the browser's permission prompt and
> a first-run disclosure. Rationale in `plan/features/families/` (FM-15) and
> `plan/features/holiday-stage/` (HS-15).
- ~~**trip_category_settings** — unique index (trip_id, category). *admin-console*~~ — **implemented**, with check constraints on `category` and `voting_mode`, and all five rows seeded at trip creation so a read never has to invent a default. The unique index is what makes the console's self-healing read safe under concurrency.
- **polls.decision_option_id, decided_by, decided_at, closed_at, closed_by, last_nudge_at** — recorded poll outcome + close/nudge audit; decision FK `ON DELETE SET NULL`. *polls*
- ~~**poll_options.suggestion_id** — link from a decided geographic option to its seeded region suggestion; column created at M2 without FK, constraint added at M3 by *map-suggestions*. *polls*~~ — **implemented**: the constraint `fk_poll_options_suggestion_id` (`ON DELETE SET NULL`, `use_alter` because `poll_options` is created before `suggestions`) was added at M3, so deleting a seeded region clears the option's link rather than leaving the decision banner pointing at nothing.
- ~~**comments.deleted_at** — soft delete backing the undo pattern (retention 30 days). *voting-comments*~~ — **implemented**, together with a second accepted addition, **comments.deleted_by** (uuid, nullable, FK → users `ON DELETE SET NULL`). `deleted_at` backs undo; every read filters `deleted_at IS NULL` through `models.comment.visible_comments()`, and a partial index `(subject_type, subject_id, created_at) WHERE deleted_at IS NULL` serves thread reads. `deleted_by` exists because "only the user who performed the delete may undo" is unanswerable from a request-scoped variable once the tab closes — and because an author whose comment an organiser removed must not be able to put it back. Rows past the 30-day retention window are hard-deleted by a **lazy sweep on the thread read**, the same pattern `foundation` uses for expired sessions, rather than by a scheduler nobody would install.
- **notifications type `mention`** — written by *voting-comments* when a comment mentions an on-trip user other than the author; payload carries `subject_type`, `subject_id`, `comment_id`, `author_name` and a `deep_link`. The bell that reads them is *notifications* (M6).
- **distance_cache.status (`ok`/`no_route`/`failed`), attempts** — unroutable pairs recorded once, never retried forever. *distances*
- **route_cache.is_fallback** — unroutable legs recorded once. *itinerary-timeline*
- **settings key `google_api_status`** — cached result of the admin-triggered API health probe. *admin-console*

## API conventions

- REST under `/api/v1/…`, one router per feature; plural nouns; Pydantic schemas for every request/response (auto OpenAPI).
- Session auth: httpOnly secure cookie, server-side session table or signed token; CSRF token for mutations. Login rate-limited.
- Permissions enforced in FastAPI dependencies: `require_member`, `require_family_head_or_spouse(family_id)`, `require_organiser`, `require_owner`, plus stage guards (`require_stage("planning", "holiday")`; End stage rejects all mutations except an organiser's stage-change).
  - `require_organiser` — the trip owner (`trips.owner_user_id`) **or** a `trip_organisers` row. This is what the older docs called `require_main_admin`; every "main admin" permission in a feature document means this unless it says otherwise. `users.is_platform_admin` remains the bootstrap bypass, unchanged: the seeded account must be able to reach its own instance before any trip exists.
  - `require_owner` — the owner alone (plus the platform-admin bypass). Used **only** by the organiser-management endpoints, which live in `admin-console`. An organiser who could appoint organisers could unappoint the owner's choices, and there would be no way back.
  - `require_family_head_or_spouse(family_id)` — `head` or `spouse` of that family, or an organiser. Renamed from `require_family_admin`. Where the *target* of an action is the family's head, the route additionally refuses a spouse: the asymmetry is enforced per-action, not per-role, because a spouse may edit every other member of the family.
- `require_member` refuses any authenticated user with no family row, which includes someone mid-onboarding who has accepted a new-family invite but not yet named their family — and, from 2026-08-11, the trip's owner on a fresh install, who takes the same family-setup step without an invite. Exactly one route admits that caller — `POST /families/mine`, via `require_pending_family` — and a second route in this category is a decision to be documented, not a quiet exemption. That route is also the **only** route that creates a family, which is what makes "no family exists without a head" enforceable rather than aspirational; the bare `POST /families` create was removed on the same date. *families*
- Which top-level screen a session may see is decided server-side and returned as `auth/me`'s `next_step` (`change_password` | `setup_trip` | `setup_family` | `app`). The web shell routes on that field alone and never recomputes the gate from individual flags, so the forced password change and both first-login setup screens cannot be navigated around. *foundation* F-13
- WebSocket authenticates via the same session cookie; server broadcasts to trip-scoped rooms.

## Google API usage & cost control

| API | When called | Cache |
|---|---|---|
| Maps JS | Map render (browser) | n/a — 10k free loads/mo, our scale ≈ hundreds |
| Places Autocomplete + Details | Only inside "create suggestion" flow and on card-open (photos/details) | `place_id` persisted; details/photos re-fetched live with short in-memory TTL. ToS forbids persisting details |
| Geocoding | Once per family home address (server-side) | Forever in `families` |
| Distance Matrix | Once per (family home, suggestion) pair (server background task on suggestion create/move) | Forever in `distance_cache` |
| Directions | Once per itinerary change per leg (server) | `route_cache` |

Guardrails documented as an ops step: quota caps at free-tier thresholds in Cloud Console, billing alert, key restricted by HTTP referrer (browser key) and by IP (server key — two separate keys).
Haversine straight-line distance is computed instantly in SQL as a fallback while Distance Matrix results are pending.

## Deployment (home server)

- `deploy/docker-compose.yml`: `caddy` (serves built web + reverse-proxies `/api`, `/ws`), `api` (uvicorn), `postgres` (volume-backed). Single `.env`.
- **Network path:** Cloudflare DNS record (proxied) → origin reachable over IPv6 only is fine — Cloudflare's edge gives IPv4 visitors access and terminates TLS with an auto cert; Caddy runs with a Cloudflare origin cert or HTTP-only behind the tunnel/proxy.
- HTTPS is mandatory end-to-end for the product to function: browser geolocation, PWA install, service workers, and Web Push all require a secure context.
- Backups: nightly `pg_dump` to the host volume (documented in deploy README); attachments included.
- **Data location (changed 2026-08-11):** Postgres and attachments are bind-mounted to `data/postgres` and `data/attachments`, relative to the compose file, at the owner's request so the data is visible in a file browser rather than sealed inside Docker's VM disk. `PGDATA` is a subdirectory of the mount because Postgres cannot `chmod` a bind mount's root. This trades durability guarantees for visibility — Postgres assumes POSIX permissions, file locking and honest `fsync`, and a Docker Desktop or SMB bind mount supplies none of them reliably. Caddy's certificate store stays a named volume. Failure modes and the revert are in `deploy/README.md` ("Where the data lives").
- First-run: Alembic migrations auto-apply; seed creates `admin`/`admin` with `must_change_password=true` and one trip in `planning`.

## Migration policy (set 2026-08-11)

**Pre-launch there is exactly one Alembic revision — `server/alembic/versions/0001_schema.py`
— and every schema change edits it in place.** No second migration file is created. After an
edit, drop and recreate the dev database; `kindred_test` rebuilds itself on the next pytest
run (`tests/conftest.py` drops and recreates the schema from the models each session).

The reasoning: nothing is deployed, so an incremental chain would record a history of
decisions that never happened to anyone's data, and a reader wanting to know the shape of one
table would have to reconstruct it from four files. One file that says what the schema *is*
beats four that say how it got here, when how it got here is a fiction.

**This reverses at the first production deploy.** At that moment `0001_schema.py` freezes,
`0002` begins the real chain, and the standard discipline applies: never edit an applied
migration, because from then on an applied migration is a fact about somebody's data rather
than a draft. Whoever ships that deploy is responsible for flipping this note and the
matching rule in `CLAUDE.md`.

The models are the other half of the contract. Every constraint and index in the migration is
mirrored in the SQLAlchemy `__table_args__`, because the test suite builds its schema with
`create_all` rather than by migrating: a constraint declared in only one of the two would be
enforced in production and absent under pytest, which is precisely where it most needs to
hold. The two are comparable down to constraint *names*, and were diffed when they were
consolidated.

## Realtime & offline

- WebSocket reconnect with resume (client sends last-seen notification id).
- Service worker (see `pwa-push`) precaches the app shell and caches the current itinerary + key info (addresses, notes) for offline reading in dead zones; mutations queue is **out of scope v1** (read-only offline).

## Testing strategy

- `server/tests/`: pytest + httpx AsyncClient against a temp Postgres (docker); every router gets happy-path + permission-denied + stage-guard tests. Services with external calls (`google.py`, `weather.py`, `push.py`) are wrapped in interfaces and faked in tests.
- `web/`: Vitest + Testing Library for chart widgets, voting components, and permission-gated UI; Playwright smoke (login → create suggestion → vote → confirm → itinerary shows it) run against compose stack.
- `web/e2e/`: the Playwright harness this line pointed at in theory until F-? — now built. `npm run e2e` (from `web/`) brings up an isolated copy of the full compose stack (its own project name, ports, and throwaway volumes — see `web/e2e/README.md`), seeds it via `scripts/seed_demo.py`, runs a small set of load-bearing smokes (fresh-install onboarding gate, cross-family privacy on the families list, join-invite registration, a `/ws` liveness check), and tears the stack down. Deliberately not part of `npm run verify` (verify stays fast and network-free) or of CI's default gate — it is what a milestone runs before being called "verified by hand" no longer, in place of the ad hoc browser checks features had been doing. Add a feature's own smoke there instead of re-describing one here.
