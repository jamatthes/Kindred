# foundation — Requirements

**Milestone:** M0. **Reads first:** `plan/overview.md`, `plan/architecture.md`,
`plan/design-system.md`, `CLAUDE.md`.

Foundation is the scaffold everything else stands on: the monorepo, the database and
migration pipeline, session-cookie authentication, the seeded admin account, the settings
table, theme persistence, the WebSocket skeleton, and the permission and stage-guard
dependencies that every later feature reuses.

Foundation deliberately ships **no product features**. It ships the shell, the login, and
the enforcement primitives.

## User stories

### F-1 — Developer: run the whole stack with one command

**As a developer, I can start the full stack with `docker compose -f deploy/docker-compose.yml up`.**

- `deploy/docker-compose.yml` defines three services: `caddy` (serves the built web bundle
  and reverse-proxies `/api` and `/ws`), `api` (uvicorn running the FastAPI app), and
  `postgres` (volume-backed).
- A single `deploy/.env` supplies all secrets; `deploy/.env.example` lists every key with a
  safe placeholder and a one-line comment.
- On first boot the API applies Alembic migrations automatically before accepting traffic.
- `GET /api/v1/health` returns `200` with the app version and database connectivity status.
- The web app is reachable on the configured host and renders the login screen.
- If `postgres` is not yet ready, `api` retries rather than crash-looping permanently.

### F-2 — Developer: run the API and web app in dev mode

**As a developer, I can run the server and web app separately for fast iteration.**

- `cd server && uvicorn app.main:app --reload` serves the API with interactive docs at
  `/docs`.
- `cd web && npm run dev` serves the PWA shell with hot module reload and proxies `/api`
  and `/ws` to the dev API.
- Both read configuration from environment variables, with dev-safe defaults where a value
  is not a secret.

### F-3 — Logged-out visitor: log in

**As a logged-out visitor, I can sign in with a username and password.**

- The login form has username and password fields, both required, validated on blur.
- A correct credential pair sets an httpOnly, `Secure`, `SameSite=Lax` session cookie and
  returns the current user record.
- An incorrect pair returns `401` with a single generic message ("Incorrect username or
  password") — the response never reveals whether the username exists.
- Passwords are verified against an argon2 hash. No other hash algorithm is accepted.
- After five failed attempts for the same username within the configured window, further
  attempts for that username return `429` until the window expires. The same limit applies
  per client IP.
- The error message appears beneath the field as text, never as colour alone.

### F-4 — Logged-in user: stay logged in, and log out

**As a logged-in user, my session persists across page reloads, and I can end it.**

- `GET /api/v1/auth/me` returns the current user (id, username, display name, platform-admin
  flag, must-change-password flag, theme preference, family membership) or `401`.
- The web shell calls it on load and routes to the login screen on `401`.
- `POST /api/v1/auth/logout` revokes the server-side session and clears the cookie;
  subsequent requests with the old cookie return `401`.
- Sessions expire after the configured TTL. An expired session behaves exactly like no
  session.

### F-5 — Seeded admin: forced password change on first login

**As the seeded platform admin, I am required to change the password before I can use anything else.**

- First run seeds a user `admin` with password `admin`, `is_platform_admin = true` and
  `must_change_password = true`, and one trip in stage `planning`.
- While `must_change_password` is true, every API route returns `403` with a machine-readable
  code `password_change_required`, except `auth/me`, `auth/logout`, `auth/password` and
  `health`.
- The web app routes such a user to a dedicated change-password screen with no way to
  navigate away other than logging out.
- Changing the password requires the current password, a new password, and a confirmation
  that matches. The new password must differ from the current one.
- Minimum password length is 10 characters; the rule is stated on screen before submission,
  not only on error.
- On success `must_change_password` is cleared, all **other** sessions for that user are
  revoked, the current session remains valid, and the user lands on the app home.
- Seeding is idempotent: restarting the stack does not reset an admin who has already
  changed their password.

### F-6 — Any user: change my own password

**As a logged-in user, I can change my own password at any time.**

- Same endpoint and same rules as F-5.
- Supplying the wrong current password returns `400` and does not change anything.
- On success all other sessions for that user are revoked.

### F-7 — Any user: choose a theme that sticks

**As a logged-in user, I can choose light, dark, or system, and my choice follows me to any device.**

- The preference is stored on the user record (`users.theme_pref`) with values `light`,
  `dark`, `system`; default `system`.
- `PATCH /api/v1/me/preferences` persists it and returns the updated value.
- The web shell applies `data-theme="light"` or `data-theme="dark"` to `<html>`; `system`
  follows `prefers-color-scheme` and updates live when the OS setting changes.
- The applied theme is correct on first paint after a reload, with no flash of the wrong
  theme.
- A logged-out visitor gets `system` behaviour, held in local storage only.

### F-8 — Any user: a live connection to the server

**As a logged-in user, my browser holds an authenticated WebSocket connection to the server.**

- `/ws` accepts a connection only when the request carries a valid session cookie; otherwise
  it closes with a policy-violation code.
- On connect the server joins the socket to the room for the user's current trip.
- The server sends a `hello` frame containing the connection id, the user id, the trip id
  and the current sequence number.
- Heartbeats: the client sends `ping` on an interval and the server replies `pong`; a socket
  with no traffic beyond the timeout is closed.
- The client reconnects with exponential backoff and resumes by sending the last sequence
  number it saw.
- Foundation ships the transport and the envelope only. Feature events are defined by the
  features that emit them.

### F-9 — Developer: permission and stage enforcement primitives

**As a developer, I can gate any route with a dependency rather than ad-hoc checks.**

- `require_member` — any authenticated user who belongs to a family on the current trip.
- `require_family_admin(family_id)` — the requesting user is an `admin` in that family, or
  is the main admin.
- `require_main_admin` — the requesting user is the trip owner / platform admin.
- `require_stage(*stages)` — rejects with `409` when the trip's stage is not in the allowed
  set.
- All four are FastAPI dependencies. No permission logic lives in the frontend; the frontend
  only hides what the backend would refuse.
- Every dependency has a unit test covering the allow case and the deny case.

### F-10 — Developer: mutations are CSRF-protected

**As a developer, every state-changing request is protected against cross-site forgery.**

- A CSRF token is issued alongside the session and readable by the frontend (double-submit
  pattern: non-httpOnly cookie plus `X-CSRF-Token` header).
- Any `POST`, `PUT`, `PATCH` or `DELETE` without a matching token returns `403`.
- `GET` and `HEAD` are exempt.
- Login itself issues a fresh token; logout invalidates it.

### F-11 — Any user: an app shell that works on phone and desktop

**As a user, the app frame is usable on both a phone and a large screen.**

- Desktop: slim left navigation rail, main content area, space reserved for the right side
  panel at roughly a 62/38 split.
- Mobile: bottom tab navigation, full-bleed content, side-panel content presented as bottom
  sheets.
- The shell is an installable PWA skeleton: manifest, icons, and a registered service worker
  that precaches the app shell. Offline data caching belongs to `pwa-push`, not here.
- All spacing uses the 5 / 8 / 13 / 21 / 34 / 55 scale. No component contains a raw hex
  colour or a magic pixel value.

> NOTE: the DesignSync pass happens *after* M0 (see `plan/overview.md`). Foundation
> therefore ships the token *structure* — primitive, semantic and component layers — with
> provisional values. It must not lock a palette. Because every component references only
> semantic tokens, DesignSync changes values in one file and nothing else.

### F-12 — Developer: platform settings exist and are readable

**As a developer, I can read and write singleton platform configuration.**

- The `settings` table stores key/value rows.
- Seeded keys: `instance_name`, `registration_open`, `invite_only`.
- `GET /api/v1/settings` returns the small public subset needed before login (instance name,
  whether self-registration is open). Everything else requires the main admin and is owned by
  `admin-console`.

## Permissions

Foundation's own surface only. Feature permissions live in each feature's doc.

| Action | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| `GET /health` | yes | yes | yes | yes |
| `GET /settings` (public subset) | yes | yes | yes | yes |
| Log in | yes | yes | yes | yes |
| Log out | yes | yes | yes | no |
| `GET /auth/me` | yes | yes | yes | no (401) |
| Change own password | yes | yes | yes | no |
| Read/write own theme preference | yes | yes | yes | no (local only) |
| Open WebSocket `/ws` | yes | yes | yes | no |
| Read another user's record | via `admin-console` | no | no | no |
| Write platform settings | via `admin-console` | no | no | no |

While `must_change_password` is true, every row above except health, `auth/me`,
`auth/logout` and `auth/password` returns `403 password_change_required` regardless of role.

## Stage availability

| Capability | Planning | Holiday | End |
|---|---|---|---|
| Log in / log out | yes | yes | yes |
| Change own password | yes | yes | yes |
| Change own theme preference | yes | yes | yes |
| WebSocket connection | yes | yes | yes |
| Any other mutation | per feature | per feature | rejected (`409`) except main-admin stage change |

Foundation supplies `require_stage`; End-stage read-only enforcement is achieved by every
feature applying it. Foundation's own mutations (password, theme, session) are exempt because
they are account operations, not trip data — this exemption is deliberate and must be
preserved.

## Out of scope

- Families, invites, and registration — `families`.
- Trip settings, stage transitions, instance-settings editing UI, platform stats —
  `admin-console`.
- Any poll, suggestion, vote, comment, itinerary or map feature.
- Notification storage, delivery, and the bell UI — `notifications`.
- Web Push, offline data caching, install prompts — `pwa-push`.
- Email of any kind, including password-reset email. v1 has no mail transport; a forgotten
  admin password is recovered by the main admin resetting it in `admin-console`.
- The final palette, type ramp and visual identity — DesignSync pass after M0.
- File uploads and attachments.
- Multi-trip UI. The schema carries `trip_id` everywhere; the v1 shell resolves a single
  active trip.
