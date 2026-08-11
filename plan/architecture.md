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
│   ├── alembic/         # migrations
│   └── tests/
├── web/                 # React + Vite PWA
│   └── src/
│       ├── design/      # tokens.css, themes, primitives
│       ├── charts/      # own chart widget library
│       ├── features/    # one dir per feature (mirrors plan/features)
│       ├── map/         # Google Maps wrapper components
│       └── app/         # shell, routing, ws client, api client
├── deploy/
│   ├── docker-compose.yml   # web (caddy+static), api, postgres
│   ├── Caddyfile
│   └── .env.example         # DB creds, GOOGLE_MAPS_API_KEY, VAPID keys, SECRET_KEY
└── legacy notes: reference app lives at E:\GitRepos\palantir-for-family-trips (NOT copied here)
```

## Database schema (multi-trip-ready; v1 UI uses one trip)

All tables `id` (uuid pk), `created_at`, `updated_at` unless noted. FKs implied by names.

### Identity
- **users** — username, password_hash (argon2), display_name, must_change_password (bool, seeds true for `admin`), theme_pref (`light`/`dark`/`system`), locale, is_platform_admin (bool)
- **families** — trip_id, name, color (token slot, used for map pins/labels), home_address (text), home_lat/home_lng (nullable until geocoded), home_geocoded_at
- **family_members** — family_id, user_id, role (`admin`/`member`) — the per-family admin
- **invites** — family_id (nullable = invite creates a new family), token, expires_at, created_by, used_by (nullable)

### Trip + configuration
- **trips** — name, stage (`planning`/`holiday`/`end`), start_date/end_date (nullable in planning), owner_user_id (main admin), timezone
- **trip_category_settings** — trip_id, category (`poll`/`region`/`accommodation`/`activity`/`meal`), voting_mode (`score`/`thumbs`)
- **settings** — key/value platform config (singleton rows: instance name, registration open, etc.)

### Deciding
- **polls** — trip_id, title, description, kind (`score_matrix`/`options`), status (`open`/`closed`), created_by, allow_member_options (bool)
- **poll_options** — poll_id, label, created_by, lat/lng + place_id (nullable — geographic options become map overlays), sort
- **poll_scores** — poll_id, option_id, user_id, score (int 0–10) or thumb (`up`/`down`/null per voting_mode); unique (option_id, user_id)
- **suggestions** — trip_id, type (`region`/`accommodation`/`activity`/`meal`), title, notes, status (`proposed`/`shortlisted`/`approved`/`scheduled`/`rejected`), created_by, lat/lng (point types), geometry_geojson (regions: circle/polygon), place_id (nullable), place_snapshot_json (user-authored fields only — name/address as entered; Google details are re-fetched live, per ToS), external_url (Airbnb links etc.)
- **suggestion_votes** — suggestion_id, user_id, score (0–10) or thumb, unique (suggestion_id, user_id)
- **comments** — polymorphic: subject_type (`suggestion`/`poll`/`itinerary_item`), subject_id, author_id, body (with @mention markup), edited_at (nullable)

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
- **notifications** — recipient_user_id, type, payload_json (deep-link target), read_at (nullable)
- **push_subscriptions** — user_id, endpoint (unique), p256dh, auth, user_agent, last_used_at, failure_count, created_at
- **attachments** — subject_type/subject_id, uploader_id, file path (local volume), mime, width/height; used for photos on suggestions/check-ins/archive

### Approved additions (proposed in feature design docs, accepted 2026-08-10)

These originated as PROPOSED ADDITION items in `plan/features/*/design.md` and are approved;
the feature docs carry the rationale.

- **sessions** (new table) — server-side sessions (revocation on password reset). *foundation*
- **login_attempts** (new table) — login rate limiting. *foundation*
- **trip_stage_transitions** (new table) — audit of who changed stage and when. *admin-console*
- **notification_preferences** (new table) — user_id, category, enabled; absent row = enabled. *notifications*
- **users.last_login_at** — admin console visibility. *admin-console*
- **families.home_locality, geocode_status, geocode_error** — locality shown to other families without leaking the street address; geocode failure states. *families*
- **family_members** — unique index on user_id (a user belongs to one family). *families*
- **invites.trip_id, token_hash, revoked_at, used_at** — hashed single-use invite tokens. *families*
- **trip_category_settings** — unique index (trip_id, category). *admin-console*
- **polls.decision_option_id, decided_by, decided_at, closed_at, closed_by, last_nudge_at** — recorded poll outcome + close/nudge audit; decision FK `ON DELETE SET NULL`. *polls*
- **poll_options.suggestion_id** — link from a decided geographic option to its seeded region suggestion; column created at M2 without FK, constraint added at M3 by *map-suggestions*. *polls*
- **comments.deleted_at** — soft delete backing the undo pattern (retention 30 days). *voting-comments*
- **distance_cache.status (`ok`/`no_route`/`failed`), attempts** — unroutable pairs recorded once, never retried forever. *distances*
- **route_cache.is_fallback** — unroutable legs recorded once. *itinerary-timeline*
- **settings key `google_api_status`** — cached result of the admin-triggered API health probe. *admin-console*

## API conventions

- REST under `/api/v1/…`, one router per feature; plural nouns; Pydantic schemas for every request/response (auto OpenAPI).
- Session auth: httpOnly secure cookie, server-side session table or signed token; CSRF token for mutations. Login rate-limited.
- Permissions enforced in FastAPI dependencies: `require_member`, `require_family_admin(family_id)`, `require_main_admin`, plus stage guards (`require_stage("planning", "holiday")`; End stage rejects all mutations except admin stage-change).
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
- Backups: nightly `pg_dump` to the host volume (documented in deploy README); attachments volume included.
- First-run: Alembic migrations auto-apply; seed creates `admin`/`admin` with `must_change_password=true` and one trip in `planning`.

## Realtime & offline

- WebSocket reconnect with resume (client sends last-seen notification id).
- Service worker (see `pwa-push`) precaches the app shell and caches the current itinerary + key info (addresses, notes) for offline reading in dead zones; mutations queue is **out of scope v1** (read-only offline).

## Testing strategy

- `server/tests/`: pytest + httpx AsyncClient against a temp Postgres (docker); every router gets happy-path + permission-denied + stage-guard tests. Services with external calls (`google.py`, `weather.py`, `push.py`) are wrapped in interfaces and faked in tests.
- `web/`: Vitest + Testing Library for chart widgets, voting components, and permission-gated UI; Playwright smoke (login → create suggestion → vote → confirm → itinerary shows it) run against compose stack.
