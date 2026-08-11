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

- `GET /api/v1/auth/me` returns the current user (id, username, first name, last name,
  display name, avatar, platform-admin flag, must-change-password flag, theme preference,
  family membership, and the `next_step` onboarding gate of F-13) or `401`.
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
- **There is no minimum password length.** A password must only be non-empty and different
  from the current one. Both rules are stated on screen before submission, not only on error.

> NOTE (changed 2026-08-11): this previously required 10 characters. Removed at the owner's
> request — this is a private, invite-only instance for one family group, and a rule that
> pushes a grandparent towards a written-down password is not obviously a net gain. The
> mitigations that actually carry the weight here are the per-username **and** per-IP login
> rate limits (F-3), argon2 hashing, and the absence of any open sign-up. A 1024-character
> ceiling remains, which is not a policy limit but a denial-of-service guard: argon2 hashes
> whatever it is given, and an unbounded field would let one request burn arbitrary CPU.
- On success `must_change_password` is cleared, all **other** sessions for that user are
  revoked, the current session remains valid, and the user lands on whatever `auth/me` says
  comes next (see F-13). In M0 that is the app home; from M1 it is the trip setup screen
  (`plan/features/admin-console/requirements.md`, AC-0).
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
  A user with no family row is **not** a member and is refused with `403 not_on_trip`. This
  is deliberate and covers three distinct people: someone removed from the trip, someone
  whose family was deleted, and someone who has accepted a new-family invite but has not yet
  named their family (see F-13). The refusal code is the same; the onboarding state that
  distinguishes them comes from `auth/me`, not from the error.
- `require_family_admin(family_id)` — the requesting user is an `admin` in that family, or
  is the main admin.
- `require_main_admin` — the requesting user is the trip owner / platform admin.
- `require_stage(*stages)` — rejects with `409` when the trip's stage is not in the allowed
  set.
- All four are FastAPI dependencies. No permission logic lives in the frontend; the frontend
  only hides what the backend would refuse.
- Every dependency has a unit test covering the allow case and the deny case.

> NOTE: because `require_member` refuses a family-less user, any route that such a user must
> be able to call during onboarding cannot use it. There is exactly one such route —
> "create my own family" — and `families` defines it with its own dependency
> (`require_pending_family`). Adding a second route in this category needs a decision, not a
> quiet exemption.

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

### F-13 — Developer: one server-owned answer to "what does this user see next"

**As a developer, the server decides which top-level screen a session is entitled to, and the
client renders that answer rather than inferring it.**

- `auth/me` carries a single `next_step` field with exactly one of:
  `change_password` | `setup_trip` | `setup_family` | `app`.
- The order of precedence is fixed and evaluated server-side:
  1. `must_change_password` is true → `change_password`.
  2. The user is the main admin and the trip is not yet configured (no `name`, or no
     `timezone`) → `setup_trip` (`admin-console` AC-0).
  3. The user has no family row and either holds a consumed new-family invite **or is the
     trip's owner** → `setup_family` (`families` FM-13). Revised 2026-08-11: the owner used to
     be exempt from this step and reached `app` with no family; see the NOTE in
     `plan/features/foundation/design.md`. The owner's full order is therefore
     `change_password` → `setup_trip` → `setup_family` → `app`.
  4. Otherwise → `app`.
- The web shell routes solely on `next_step`. It never computes the gate from the individual
  flags, so the client and the server cannot disagree about which screen is legal.
- A user who abandons an onboarding screen and returns later gets the same `next_step`,
  because it is derived from stored state rather than from a one-shot redirect. This is what
  makes "you come back to this screen until it is done" true rather than aspirational.
- Every value except `app` is terminal for navigation: the shell renders that screen and no
  other, with logging out as the only escape.
- A user with no family who does **not** hold a new-family invite **and is not the owner**
  (removed from the trip, or their family was deleted) gets `app`, and the app shows the "you
  are not on this trip" state. They are not sent to family setup — they were not invited to
  create a family, and a setup screen there would let anyone removed from the trip re-admit
  themselves. This is the one family-less `app`, and it is a family taken away rather than an
  account admitted without one.

> NOTE: foundation ships the field and the routing gate in M0, where only `change_password`
> and `app` can ever be returned. `setup_trip` and `setup_family` become reachable when
> `admin-console` and `families` land in M1. Shipping the mechanism in M0 is what stops the
> forced-password-change screen from being special-cased, and stops M1 from having to rewrite
> the shell's routing.

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
- File uploads and attachments, including profile pictures. The upload path and the avatar
  itself are owned by `families` (FM-14); foundation only carries the avatar reference on the
  user record it already returns from `auth/me`.
- Multi-trip UI. The schema carries `trip_id` everywhere; the v1 shell resolves a single
  active trip.
