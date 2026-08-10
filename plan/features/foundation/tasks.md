# foundation — Tasks

**Milestone M0.** Execute in order. Each phase ends with a `Verify:` line — do not start the
next phase until it passes. Read `requirements.md` and `design.md` in this directory first.

## Phase 1 — Repo skeleton

- [ ] Create the directory tree from `design.md` (`server/`, `web/`, `deploy/`), with a
      `.gitkeep` in each empty directory (`server/app/services/`, `web/src/charts/`,
      `web/src/map/`).
- [ ] Add root `.gitignore`: `.env`, `__pycache__/`, `.venv/`, `node_modules/`, `dist/`,
      `.pytest_cache/`, `*.pyc`.
- [ ] `server/pyproject.toml` with dependencies: `fastapi`, `uvicorn[standard]`,
      `sqlalchemy[asyncio]>=2`, `asyncpg`, `alembic`, `pydantic>=2`, `pydantic-settings`,
      `argon2-cffi`, `python-multipart`; dev extras `pytest`, `pytest-asyncio`, `httpx`.
- [ ] `web/` scaffold via Vite React + TypeScript; add `tailwindcss@4`, `vite-plugin-pwa`,
      `vitest`, `@testing-library/react`.
- [ ] `server/app/core/config.py` — a `pydantic-settings` class covering every key in the
      `.env.example` table in `design.md`. Fail fast when `SECRET_KEY` is unset or equals the
      placeholder.
- [ ] `deploy/.env.example` with every key, placeholder and comment from `design.md`.

**Verify:** `cd server && python -c "from app.core.config import settings; print(settings.database_url)"`
fails with a clear message when `SECRET_KEY` is the placeholder, and succeeds when it is set.
`cd web && npm run build` produces `dist/`.

## Phase 2 — Database, migrations, models

- [ ] `server/app/models/base.py` — declarative base with `id` (uuid pk, server default),
      `created_at`, `updated_at` mixin.
- [ ] Models: `user.py` (`users`, `user_settings`), `session.py` (`sessions`,
      `login_attempts` — both PROPOSED ADDITION per `design.md`), `trip.py` (`trips`),
      `setting.py` (`settings`), plus bare `families` and `family_members` tables exactly as
      specified in `plan/architecture.md`.
- [ ] Alembic init; `alembic/env.py` reads `DATABASE_URL` from settings and imports all
      models so autogenerate sees them.
- [ ] Generate migration `0001_foundation`. Review the generated file by hand — check uuid
      defaults, the unique index on lowercased `username`, indexes on `sessions.user_id`,
      `sessions.expires_at`, `login_attempts.created_at`, and the unique constraint on
      `user_settings.user_id`.
- [ ] Wire migrations to run on API startup before the server accepts traffic.

**Verify:** `docker compose -f deploy/docker-compose.yml up postgres -d`, then
`cd server && alembic upgrade head` succeeds; `alembic downgrade base` then `upgrade head`
succeeds again. `\dt` in psql lists `users`, `user_settings`, `sessions`, `login_attempts`,
`trips`, `settings`, `families`, `family_members`.

## Phase 3 — Security core and seed

- [ ] `core/security.py` — argon2 hash/verify, `check_needs_rehash`, a fixed dummy hash for
      constant-time rejection of unknown usernames, and token generation
      (`secrets.token_urlsafe(32)` plus sha256 storage).
- [ ] `core/sessions.py` — create, load-by-cookie-value, touch `last_seen_at` (at most once a
      minute), revoke one, revoke all-for-user-except-current, lazy sweep of expired rows.
- [ ] `core/ratelimit.py` — record an attempt, count trailing-60s failures by username and by
      IP, clear on success, lazy sweep of rows older than an hour.
- [ ] `core/seed.py` — idempotent: create the `admin` user (argon2 hash of
      `SEED_ADMIN_PASSWORD`, `is_platform_admin=true`, `must_change_password=true`) only when
      no user exists; create one trip in `planning` owned by that user only when no trip
      exists; upsert `settings` rows `instance_name`, `registration_open`, `invite_only`.
- [ ] Call the seed from the app lifespan, after migrations.

**Verify:** `pytest server/tests/test_security.py` — argon2 round-trip passes, a wrong
password fails, and verifying an unknown user still consumes a hash operation. Start the API
twice against the same database and confirm in psql that exactly one `admin` row and one trip
row exist.

## Phase 4 — Schemas and auth router

- [ ] `schemas/common.py` — the error envelope `{detail: {code, message}}` and a shared
      `ErrorOut`.
- [ ] `schemas/auth.py`, `schemas/user.py` — `LoginIn`, `PasswordChangeIn`,
      `PreferencesIn/Out`, `UserOut` exactly as sketched in `design.md`.
- [ ] `routers/health.py` — `GET /api/v1/health` with a real database ping.
- [ ] `routers/auth.py` — login (rate-limited, revokes any prior session, issues session +
      CSRF cookies), logout, `me`, `password`.
- [ ] `routers/settings.py` — `GET /api/v1/settings`, public subset only.
- [ ] `routers/me.py` — `GET`/`PATCH /api/v1/me/preferences`.
- [ ] Register a global exception handler so every `HTTPException` renders the shared error
      envelope.

**Verify:** open `/docs`. Manually: `POST /auth/login` with `admin`/`admin` returns a user
with `must_change_password: true`; `GET /auth/me` returns the same user; six rapid bad logins
return `429` with `Retry-After`; `POST /auth/password` with the correct current password
returns `204` and a subsequent `GET /auth/me` shows `must_change_password: false`.

## Phase 5 — Dependencies, CSRF, stage guards

- [ ] `deps.py` — `get_session`, `current_user`, `enforce_password_change`, `require_member`,
      `require_family_admin(family_id)`, `require_main_admin`, `require_stage(*stages)`, per
      `design.md`.
- [ ] CSRF middleware — reject unsafe methods whose `X-CSRF-Token` header does not match the
      session's `csrf_token`; exempt `GET`/`HEAD`/`OPTIONS` and the login route.
- [ ] Apply `enforce_password_change` as a router-level dependency on every router except
      `auth` and `health`, so future routers inherit it.
- [ ] Add a temporary probe route per dependency (`/api/v1/_probe/member`, `/_probe/main-admin`,
      `/_probe/stage`) guarded only by that dependency, for tests. Mark them clearly and
      remove them at the end of Phase 8.

**Verify:** `pytest server/tests/test_deps.py` — each dependency has an allow test and a deny
test; `require_stage` returns `409` when the trip is set to `end`; a `POST` without the CSRF
header returns `403`; every non-auth route returns `403 password_change_required` for a user
with the flag set.

## Phase 6 — WebSocket skeleton

- [ ] `ws.py` — `/ws` endpoint, cookie authentication in the handshake, close `1008` on
      failure, the in-process room registry keyed by `trip_id`, and the
      `{type, trip_id, seq, ts, payload}` envelope.
- [ ] `hello` on connect; `ping`/`pong`; idle timeout close.
- [ ] `resume` handling: respond `resync` (no event log in v1, per `design.md`).
- [ ] Export `broadcast(trip_id, type, payload)` and `send_user(user_id, type, payload)` for
      later features; add a docstring listing the event names reserved in
      `plan/architecture.md`.
- [ ] Clean up the registry on disconnect, including on exception paths.

**Verify:** `pytest server/tests/test_ws.py` — a connection without a cookie is closed with
`1008`; an authenticated connection receives `hello`; `ping` returns `pong`; a manual
`broadcast` reaches a connected test client; disconnecting removes the room entry.

## Phase 7 — Design tokens and app shell

- [ ] `web/src/design/tokens.primitives.css` — raw scales only: colour ramps, spacing
      `5 8 13 21 34 55`, type `16 20 26 42 68`, radii, shadows.
- [ ] `web/src/design/tokens.semantic.css` — the semantic names listed in
      `plan/design-system.md`, including `--family-1…8` and `--scale-pref-0…10`, with a
      separate tuned `[data-theme="dark"]` block (not an inversion).
- [ ] Bind Tailwind 4 `@theme` to the semantic layer so utilities resolve to tokens.
- [ ] `app/apiClient.ts` — base URL, JSON handling, automatic `X-CSRF-Token`, one retry after
      a `csrf_invalid`, and a typed error object carrying `code`.
- [ ] `app/session.ts` — `auth/me` on load, in-memory user context, routing rules: no user →
      login; `must_change_password` → the change screen; otherwise the app.
- [ ] `app/wsClient.ts` — connect after a successful `auth/me`, exponential backoff with
      jitter (1s → 30s), `resync` handling, a subscribe API for feature code, and a
      reconnecting indicator that appears only after the second consecutive failure.
- [ ] `app/shell.tsx` — desktop nav rail + main + right side-panel slot at ~62/38; mobile
      bottom tabs + full-bleed main + a reusable `BottomSheet` with snap points.
- [ ] Theme control (Light / Dark / System) wired to `PATCH /me/preferences`, optimistic with
      rollback; the inline no-flash script in `index.html` plus a local cache of the value.
- [ ] Form primitives with all six field states; validate on blur, re-validate on change
      after the first error; error text beneath the field.
- [ ] Login screen and forced-password-change screen per `design.md`.
- [ ] PWA manifest, icons, service-worker registration precaching the app shell only.
- [ ] A CI check (lint rule or grep) that fails on a raw hex colour or an off-scale px value
      under `web/src/features/**` and `web/src/app/**`.

**Verify:** in the browser — log in as `admin`/`admin`, land on the forced-change screen,
confirm no navigation escapes it, change the password, land on home. Toggle each theme, reload,
and confirm the choice survives with no flash of the wrong theme. Resize to a phone width and
confirm the bottom tabs and a bottom sheet render with ≥ 44px targets. Stop the API and
confirm the reconnecting indicator appears only after the second failure.
`npm test` passes; the token lint check fails when a raw hex is deliberately introduced.

## Phase 8 — Deployment and hardening

- [ ] `deploy/docker-compose.yml` — `postgres` (named volume, healthcheck), `api` (built from
      `server/`, depends on the postgres healthcheck, restart policy), `caddy` (serves the
      built `web/dist`, reverse-proxies `/api` and `/ws`, WebSocket upgrade headers).
- [ ] `deploy/Caddyfile` — static file server with SPA fallback to `index.html`, the two
      proxies, sensible security headers.
- [ ] `server/Dockerfile` (multi-stage, non-root user) and `web/Dockerfile` or a build stage
      that outputs `dist` into the Caddy image.
- [ ] Startup ordering: retry the database connection with backoff for up to 60 seconds, then
      exit non-zero.
- [ ] `deploy/README.md` — first-run steps, the nightly `pg_dump` backup command including
      the attachments volume, and the Google Cloud Console guardrails from
      `plan/architecture.md` (quota caps at free-tier thresholds, a billing alert, the browser
      key restricted by referrer and the server key restricted by IP).
- [ ] Remove the `_probe` routes added in Phase 5.

**Verify:** on a clean machine, copy `.env.example` to `.env`, set `SECRET_KEY` and the
Postgres password, run `docker compose -f deploy/docker-compose.yml up --build`. The stack
comes up, `/api/v1/health` returns `200` with `db: ok`, the web app loads over the configured
host, login as `admin`/`admin` forces the password change, and the WebSocket connects (visible
in the browser network panel as a `101` upgrade). `docker compose down && up` preserves the
changed password.

## Phase 9 — Tests and handover

- [ ] `tests/conftest.py` — a temporary Postgres (docker or a per-run schema), an
      `httpx.AsyncClient` fixture, and factories for a main admin, a family admin and a plain
      member, so every later feature reuses them.
- [ ] `test_auth.py` — login success and failure, the generic error message, rate limiting,
      logout revocation, session expiry, session fixation on re-login, password change
      revoking other sessions.
- [ ] `test_deps.py`, `test_ws.py` — as verified in Phases 5 and 6.
- [ ] `test_seed.py` — idempotency across repeated runs.
- [ ] `web/`: Vitest for the theme controller, the API client's CSRF retry, and the
      permission-gated shell routing.
- [ ] Confirm every requirement F-1 to F-12 has at least one covering test or a documented
      manual verification step.

**Verify:** `cd server && pytest` is green; `cd web && npm test` is green. Tests make no
network calls to Google, NOAA or any external host.

## Hand-off notes for the next milestone

- The DesignSync pass runs **after** this milestone and before any feature UI. It changes
  values in `tokens.semantic.css` only; if it needs to touch a component, that component was
  built wrong.
- `families` owns the `families` and `family_members` tables from here; foundation created
  them bare so `require_member` could compile.
- The `sessions` and `login_attempts` tables are PROPOSED ADDITIONs to
  `plan/architecture.md`. Once implemented, add them to that document's schema section in the
  same commit — the docs are the record.
