# foundation — Design

**Reads first:** `plan/overview.md`, `plan/architecture.md`, `plan/design-system.md`,
`CLAUDE.md`, and `plan/features/foundation/requirements.md`.

## Repo scaffold

Exactly the layout in `plan/architecture.md`. Foundation creates it; later features fill it.

```
Kindred/
├── server/
│   ├── app/
│   │   ├── main.py            # app factory, router registration, lifespan
│   │   ├── deps.py            # permission + stage dependencies
│   │   ├── ws.py              # WebSocket endpoint, room registry, envelope
│   │   ├── models/            # base.py, user.py, session.py, trip.py, setting.py
│   │   ├── schemas/           # auth.py, user.py, common.py
│   │   ├── routers/           # auth.py, me.py, settings.py, health.py
│   │   ├── services/          # (empty in M0 — google.py etc. arrive with their features)
│   │   └── core/              # config.py, security.py, sessions.py, ratelimit.py, seed.py
│   ├── alembic/               # env.py, versions/
│   ├── tests/                 # conftest.py, test_auth.py, test_deps.py, test_ws.py
│   └── pyproject.toml
├── web/
│   ├── src/
│   │   ├── design/            # tokens.primitives.css, tokens.semantic.css, theme.ts
│   │   ├── charts/            # (empty in M0)
│   │   ├── features/          # auth/
│   │   ├── map/               # (empty in M0)
│   │   └── app/               # shell.tsx, routes.tsx, apiClient.ts, wsClient.ts, session.ts
│   ├── public/                # manifest.webmanifest, icons
│   ├── index.html
│   └── vite.config.ts
└── deploy/
    ├── docker-compose.yml
    ├── Caddyfile
    └── .env.example
```

> NOTE (implementation, Phase 2): two files exist that the tree above does not name.
> `models/family.py` holds the bare `families` / `family_members` tables — the tree lists
> `models/` as "base.py, user.py, session.py, trip.py, setting.py", but those tables are
> required by `require_member` (see the ordering-dependency NOTE below) and did not belong in
> any of the five. `core/db.py` holds the async engine, the session factory and the `get_db`
> request dependency. It is deliberately **not** called `get_session`: in this codebase a
> "session" is an authenticated user session (`core/sessions.py`, the `sessions` table), and
> `deps.get_session` is the dependency that loads one from the cookie. The database handle is
> `db` throughout.

Server stack: FastAPI, SQLAlchemy 2 (async, declarative with `Mapped[...]`), Alembic,
asyncpg, Pydantic v2, `argon2-cffi`, pytest + `httpx.AsyncClient`.
Web stack: React + Vite + TypeScript, Tailwind 4 (`@theme` bound to the semantic tokens),
Vitest + Testing Library, `vite-plugin-pwa` for the manifest and service-worker registration.

## Data model

All tables carry `id` (uuid pk), `created_at`, `updated_at` unless noted, per
`plan/architecture.md`.

### Existing tables used by foundation

**`users`** — as specified in `architecture.md`:
`username` (unique, citext or lowercased with a unique index), `password_hash` (argon2),
`display_name`, `must_change_password` (bool, seeds true for `admin`), `theme_pref`
(`light`/`dark`/`system`), `locale`, `is_platform_admin` (bool).

**`trips`** — `name`, `stage` (`planning`/`holiday`/`end`), `start_date`/`end_date`
(nullable in planning), `owner_user_id`, `timezone`. Foundation seeds one row in `planning`
and reads `stage` for `require_stage`. Editing trips belongs to `admin-console`.

**`settings`** — key/value platform config, singleton rows. Foundation creates the table and
seeds `instance_name`, `registration_open`, `invite_only`, and exposes the public read.

**`user_settings`** — `user_id`, `live_location_enabled` (default false), `push_enabled`.
Foundation creates the table and the row-on-user-create, but does not use the columns; they
belong to `holiday-stage` and `pwa-push`. Theme preference lives on `users.theme_pref`, not
here, per `architecture.md`.

**`family_members`** — read-only for foundation. `require_member` and
`require_family_admin` resolve membership and role through it. The table itself is created by
the `families` migration.

> NOTE: this creates an ordering dependency. Foundation's `require_member` needs
> `family_members` to exist. Resolution: the foundation migration creates `families` and
> `family_members` as bare tables (the columns listed in `architecture.md`), and the
> `families` feature adds its behaviour, endpoints and any further columns on top. Foundation
> writes no rows into them except through the seed, which creates no family — the seeded
> admin has no family until `families` ships. `require_member` therefore treats the platform
> admin as always satisfying membership.

### PROPOSED ADDITION — `sessions`

`plan/architecture.md` says "server-side session table **or** signed token". We choose the
table: revocation is required by F-5, F-6 and by `admin-console`'s password reset, and a
signed token cannot be revoked before expiry.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | not the cookie value |
| `user_id` | uuid fk → users | indexed |
| `token_hash` | text | sha256 of the opaque cookie value; the raw value is never stored |
| `csrf_token` | text | issued with the session, used for double-submit |
| `expires_at` | timestamptz | indexed |
| `revoked_at` | timestamptz null | set on logout, password change, admin reset |
| `user_agent` | text null | for a future "active sessions" view |
| `ip` | inet null | for a future "active sessions" view |
| `last_seen_at` | timestamptz | touched at most once a minute to limit write load |
| `created_at` | timestamptz | |

A session is valid when `revoked_at is null and expires_at > now()`. Expired rows are deleted
by a lazy sweep on login (delete where `expires_at < now() - 7 days`), not by a scheduler.

### PROPOSED ADDITION — `login_attempts`

Rate limiting must survive an API restart and work if the API is ever run with more than one
worker, so it is stored rather than held in memory.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `username` | text | lowercased; recorded even when no such user exists |
| `ip` | inet | |
| `succeeded` | bool | |
| `created_at` | timestamptz | indexed |

A login is refused when either `username` or `ip` has ≥ `RATE_LIMIT_LOGIN_PER_MINUTE`
failures in the trailing 60 seconds. Successful logins delete that username's recent failure
rows. A lazy sweep on login deletes rows older than one hour.

> NOTE: an in-process limiter is the simpler option and is adequate for a single-container
> home deployment. The table is preferred because it is only marginally more work and removes
> a class of surprise if the deployment ever grows a second worker. If an implementer chooses
> the in-process route instead, the behaviour in F-3 must be identical and the choice must be
> recorded here.

## REST endpoints

All under `/api/v1`. Every request and response has a Pydantic schema so `/docs` is complete.

| Method | Path | Request | Response | Permission dependency |
|---|---|---|---|---|
| GET | `/health` | — | `{status, version, db: "ok"\|"down"}` | none |
| GET | `/settings` | — | `{instance_name, registration_open, invite_only}` | none |
| POST | `/auth/login` | `{username, password}` | `{user: UserOut, csrf_token}` + `Set-Cookie` | none; rate-limited |
| POST | `/auth/logout` | — | `204` | authenticated |
| GET | `/auth/me` | — | `UserOut` | authenticated |
| POST | `/auth/password` | `{current_password, new_password}` | `204` | authenticated; exempt from the must-change interceptor |
| GET | `/me/preferences` | — | `{theme_pref, locale}` | `require_member` |
| PATCH | `/me/preferences` | `{theme_pref?, locale?}` | `{theme_pref, locale}` | `require_member` |

`UserOut`:

```
{
  id, username, display_name,
  is_platform_admin: bool,
  must_change_password: bool,
  theme_pref: "light"|"dark"|"system",
  locale: str,
  family: {id, name, color, role} | null,
  trip: {id, name, stage, start_date, end_date, timezone} | null
}
```

`family` is null until `families` ships. `trip` carries the single active trip so the shell
knows the stage without a second call.

Error envelope, used by every router in the project:

```
{"detail": {"code": "password_change_required", "message": "Change your password to continue."}}
```

Codes introduced here: `invalid_credentials` (401), `rate_limited` (429),
`password_change_required` (403), `csrf_invalid` (403), `not_authenticated` (401),
`forbidden` (403), `stage_forbidden` (409), `validation_error` (422).

## Permission and stage dependencies (`server/app/deps.py`)

- `get_session` — reads the cookie, hashes it, loads the `sessions` row, checks validity,
  touches `last_seen_at`. Returns `None` when absent or invalid.
- `current_user` — resolves the user from the session or raises `401 not_authenticated`.
- `enforce_password_change` — raises `403 password_change_required` when
  `must_change_password` is true. Applied as a **router-level** dependency on every router
  except `auth` and `health`, so a new feature router gets it by default rather than by the
  author remembering.
- `require_member` — `current_user` plus a `family_members` row for the active trip, or
  `is_platform_admin`. Raises `403 forbidden`.
- `require_family_admin(family_id)` — a dependency factory. Passes when the user has
  `family_members.role == "admin"` for that family, or is the main admin. Raises `403`.
- `require_main_admin` — passes when the user is `is_platform_admin` or `trips.owner_user_id`.
  Raises `403`.
- `require_stage(*stages)` — a dependency factory. Loads the active trip's stage and raises
  `409 stage_forbidden` when it is not in the allowed set. Applied to every mutating route in
  every feature; the End stage is thereby read-only without per-route special-casing.
- `require_csrf` — compares the `X-CSRF-Token` header against the session's `csrf_token` for
  unsafe methods. Registered as global middleware, not per-route, so nothing can forget it.

Composition rule for later features: a mutating route declares
`dependencies=[Depends(require_member), Depends(require_stage("planning", "holiday"))]` and
never checks a role inside the handler body.

## Security details

- **Hashing:** argon2id via `argon2-cffi` with library defaults, `PasswordHasher.check_needs_rehash`
  on every successful login to allow parameter upgrades later.
- **Timing:** on an unknown username, verify against a fixed dummy hash so the response time
  does not distinguish "no such user" from "wrong password".
- **Cookie:** name from `SESSION_COOKIE_NAME`, `httponly=True`, `secure=True`,
  `samesite="lax"`, `path="/"`. `secure` is unconditional — the deployment is HTTPS-only per
  `architecture.md`, and dev runs over `http://localhost`, which browsers treat as a secure
  context.
- **Cookie value:** 32 bytes from `secrets.token_urlsafe`; only its sha256 is stored.
- **CSRF cookie:** separate, non-httpOnly, same lifetime, so the SPA can read and echo it.
- **Secrets:** `SECRET_KEY` is required at startup; the app refuses to boot if it is unset or
  equal to the placeholder in `.env.example`.

## WebSocket skeleton (`server/app/ws.py`)

Single endpoint `/ws`. Authenticates with the session cookie in the handshake; on failure
closes with `1008`.

Connection registry: an in-process `dict[trip_id, set[Connection]]`, each `Connection`
holding the socket, `user_id`, `family_id` and the last acknowledged sequence number. Single
API container, so no cross-process bus is needed.

> NOTE: this registry is per-process. If the deployment ever runs multiple API workers, a
> Redis or Postgres `LISTEN/NOTIFY` fan-out is required. Documented here so the assumption is
> visible; not built in v1.

Envelope, server → client:

```
{"type": "poll.vote.updated", "trip_id": "...", "seq": 1421, "ts": "...", "payload": {...}}
```

Client → server frames in v1: `{"type": "ping"}` and
`{"type": "resume", "last_seq": 1400}`. The client never mutates over the socket — all writes
go through REST, and the socket is a broadcast channel only. This keeps permission
enforcement in one place.

Sequence numbers are per-trip and monotonic, held in memory and seeded from a counter at
startup. `resume` replays nothing in v1 (there is no event log); the server responds with
`{"type": "resync"}` and the client refetches the views it has open. This is honest about the
guarantee: at-most-once delivery with a refetch fallback, not an event log.

Events reserved by `architecture.md` and emitted by later features: `poll.vote.updated`,
`suggestion.vote.updated`, `suggestion.created`, `notification.new`, `location.updated`,
`stage.changed`, `presence.updated`. Vote events are namespaced by domain — polls and
suggestions emit distinct types, never a shared `vote.updated`. Foundation emits `hello`,
`pong`, `resync` — and owns `presence.updated`: the socket registry broadcasts
`{user_id, online}` on connect/disconnect with a short debounce (refreshes must not flap),
and exposes a REST snapshot of currently-online user ids for initial render. Presence is
ephemeral; nothing is persisted.

Broadcast helper exposed for features: `await ws.broadcast(trip_id, type, payload)` and
`await ws.send_user(user_id, type, payload)`.

> NOTE (implementation, Phase 6): two points this section left open.
> **1.** A user with `must_change_password` is refused the socket, closed `1008`, like any
> other non-exempt surface. `requirements.md` > Permissions lists "Open WebSocket `/ws`" in
> the table its must-change-password rule applies to, and the exemptions are named there as
> `health`, `auth/me`, `auth/logout` and `auth/password` only.
> **2.** The REST presence snapshot is `GET /api/v1/presence` → `{online_user_ids: [...]}`,
> in `routers/presence.py` (the tree above lists only auth/me/settings/health), guarded by
> `require_member`. It reads the in-process registry and touches no table — presence is never
> persisted.

## UI behaviour

Per `plan/design-system.md`. Foundation builds the frame, not the content.

**App shell — desktop.** Slim left nav rail (icon plus label, ~55px collapsed target),
main region, and a right side-panel slot that is empty in M0 but laid out at the 62/38 split
so later features drop into it without a layout rewrite. Bottom timeline panel slot exists
and is collapsed.

**App shell — mobile.** Bottom tab navigation, full-bleed main region, and a bottom-sheet
container component (drag handle, snap points at ~40% and ~90%, dismiss on backdrop tap)
that later features render into instead of the side panel. Hit targets ≥ 44px.

**Login screen.** Centred single-column card. Instance name from `GET /settings` as the
heading, so a self-hoster sees their own name before authenticating. All six field states are
styled from day one (default, hover, focus, filled, error, disabled). Validation on blur,
re-validation on change after the first error, error text beneath the field. Submit shows an
inline spinner; a sub-second wait shows no skeleton.

**Forced password change screen.** Reached automatically whenever `must_change_password` is
true, from any route. No nav rail, no tabs — only the form and a log-out link. Copy states
plainly why: the account still has its seeded password. Rules (minimum 10 characters, must
differ from current) are shown before submission. On success, a toast confirms and the user
lands on home — a toast is correct here because it confirms the user's own action and needs
no persistence.

**Theme.** A three-way control (Light / Dark / System) in the shell. Optimistic switch, then
`PATCH /me/preferences`; on failure the control rolls back and shows an inline error. To
avoid a flash of the wrong theme, a small blocking inline script in `index.html` reads a
locally cached preference and sets `data-theme` before first paint; the server value
reconciles on load and updates the cache.

**Loading.** Skeletons for structural loads (the shell while `auth/me` resolves), spinners
only for sub-second inline waits.

**Empty states.** M0 has one: the home region before any feature exists — a short line naming
the trip and its stage, so the shell never renders a blank rectangle.

**Motion.** 150–250ms, standard easing, applied to sheet-up, panel-in and toast. Honours
`prefers-reduced-motion` by dropping to opacity-only or none.

**Tokens.** `web/src/design/tokens.primitives.css` holds raw scales; `tokens.semantic.css`
maps them to `--color-bg`, `--color-surface`, `--color-surface-raised`, `--color-border`,
`--color-text`, `--color-text-muted`, `--color-accent`, `--color-success`, `--color-warning`,
`--color-danger`, `--color-info`, `--family-1…8`, `--scale-pref-0…10`, spacing, radii,
shadows. Dark is a separate tuned block under `[data-theme="dark"]`, never a filter
inversion. A lint rule or a CI grep fails the build on a raw hex or a px value outside the
scale in `web/src/features/**` and `web/src/app/**`.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| Database unreachable at startup | API retries with backoff for up to 60s, then exits non-zero so the container restarts |
| Database unreachable at request time | `503` with code `db_unavailable`; `/health` reports `db: down` |
| Alembic migration fails on boot | API refuses to serve; the error is logged in full; the container exits non-zero |
| `SECRET_KEY` unset or still the placeholder | Refuse to boot with a clear message naming `.env.example` |
| Seed runs on a non-empty database | Idempotent: create `admin` only if no user exists; create a trip only if none exists |
| Admin already changed the password, container restarts | Seed makes no change; `must_change_password` stays false |
| Login while already logged in | Old session revoked, new one issued; prevents session fixation |
| Cookie present but session revoked or expired | `401 not_authenticated`; the web client clears local state and routes to login |
| CSRF cookie missing but session valid | `403 csrf_invalid`; the client refetches `auth/me` to reissue, then retries once |
| Password change with new == current | `400` with code `password_unchanged` |
| Password shorter than 10 characters | `422 validation_error`, message beneath the field |
| Rate limit reached | `429 rate_limited` with a `Retry-After` header; the form disables submit and shows the wait |
| WebSocket connects without a session | Close `1008`; the client does not retry until `auth/me` succeeds |
| WebSocket drops | Reconnect with exponential backoff (1s → 30s cap) plus jitter; a subtle "reconnecting" indicator appears only after the second failure, so a blink is not shown to the user |
| Two tabs open, one logs out | The other receives `401` on its next call and routes to login; the socket closes |
| Trip stage is `end` | Every route guarded by `require_stage` returns `409 stage_forbidden`; the web shell renders an archive banner and hides mutating controls |
| User has no family (pre-`families`) | `require_member` passes only for the platform admin; others get `403 forbidden` with a message explaining they need an invite |
| `prefers-color-scheme` changes while `system` is selected | Theme updates live via a media-query listener |

## `.env.example` contents

Every key, with a placeholder and a one-line comment. `deploy/.env` is never committed.

| Key | Example | Purpose |
|---|---|---|
| `POSTGRES_USER` | `kindred` | Postgres role |
| `POSTGRES_PASSWORD` | `change-me` | Postgres password |
| `POSTGRES_DB` | `kindred` | Database name |
| `DATABASE_URL` | `postgresql+asyncpg://kindred:change-me@postgres:5432/kindred` | API connection string |
| `SECRET_KEY` | `generate-with-openssl-rand-hex-32` | Signing/derivation secret; boot fails if unchanged |
| `SESSION_COOKIE_NAME` | `kindred_session` | Session cookie name |
| `SESSION_TTL_HOURS` | `720` | Session lifetime (30 days) |
| `RATE_LIMIT_LOGIN_PER_MINUTE` | `5` | Failed logins per username and per IP before `429` |
| `SEED_ADMIN_USERNAME` | `admin` | Seeded platform admin |
| `SEED_ADMIN_PASSWORD` | `admin` | Seeded password; forced change on first login |
| `PUBLIC_BASE_URL` | `https://kindred.example.org` | Used for invite links and push payloads |
| `CORS_ORIGINS` | `http://localhost:5173` | Dev only; empty in production (same origin behind Caddy) |
| `GOOGLE_MAPS_BROWSER_KEY` | `` | Maps JS + Places, restricted by HTTP referrer |
| `GOOGLE_MAPS_SERVER_KEY` | `` | Geocoding, Distance Matrix, Directions, restricted by IP |
| `VAPID_PUBLIC_KEY` | `` | Web Push (`pwa-push`) |
| `VAPID_PRIVATE_KEY` | `` | Web Push |
| `VAPID_SUBJECT` | `mailto:admin@example.org` | Web Push contact |
| `ATTACHMENTS_DIR` | `/data/attachments` | Local volume for uploads |
| `TZ` | `Europe/London` | Container timezone |
| `LOG_LEVEL` | `info` | API log level |

Two separate Google keys are mandatory, per the guardrails in `plan/architecture.md`: the
browser key is referrer-restricted, the server key is IP-restricted. Keys are blank in the
example; the app must start and run without them, degrading only the features that need them.
