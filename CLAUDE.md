# Kindred — Agent Instructions

Kindred is a self-hosted, map-centric trip planner for groups of families: polls to pick a
destination, map suggestions with voting and comments, an admin-confirmed itinerary on a
timeline, and check-ins/live location during the trip. Trips move through three stages —
Planning → Holiday → End (frozen archive). FastAPI + PostgreSQL backend, React + Vite PWA
frontend, deployed via Docker Compose on a home server behind Cloudflare.

## Read before working

1. `plan/overview.md` — product, roles, decision log, milestones. **The decision log is
   binding**; don't relitigate settled choices without the user.
2. `plan/architecture.md` — repo layout, DB schema, API conventions, Google API cost rules.
3. `plan/design-system.md` — **required before ANY UI work.**
4. `plan/features/<feature>/` — `requirements.md`, `design.md`, `tasks.md` for the feature
   you're touching.

## Hard rules

- **Docs-first:** plan docs are the record. If your change alters behavior, update the
  feature's docs in the same commit. New features get a `plan/features/<name>/` dir with
  all three files before code.
- **Token-only styling:** never a raw hex color or magic px in a component — semantic
  tokens only (`plan/design-system.md`). Light AND dark must both work for anything you style.
- **Never call Google APIs in a render path.** Check the cache tables
  (`distance_cache`, `route_cache`, families' geocoded home) first; external calls happen
  in server-side services (`server/app/services/`) and results are cached per
  `plan/architecture.md`. Places details are the one exception (ToS forbids persisting
  them) — fetched on card-open only.
- **Permissions + stage guards in FastAPI dependencies**, not in frontend logic. End stage
  is read-only. Main admin > family admin > member.
- **Migrations:** any model change ships with an Alembic migration. Never edit an applied
  migration.
- **Charts:** use `web/src/charts/` widgets; do not add a chart library. Honesty rules
  (zero-baseline bars etc.) live in the widgets — don't work around them.
- **Schema is multi-trip:** every trip-scoped table carries `trip_id` even though v1's UI
  shows one trip. Don't write code that assumes a single trip id.

## Running things

- Full stack: `docker compose -f deploy/docker-compose.yml up` (postgres + api + caddy/web).
- Dev: `server/` → `uvicorn app.main:app --reload` (API docs at `/docs`);
  `web/` → `npm run dev`. Secrets in `deploy/.env` (see `.env.example`) — never commit it.
- Tests: `pytest` in `server/`; `npm test` (Vitest) in `web/`. Fake the external service
  interfaces in tests; never hit Google/NOAA from the test suite.

## Reference material

The predecessor app lives at `E:\GitRepos\palantir-for-family-trips` (do not modify; do
not copy wholesale — it's a different architecture: localStorage, no backend). Useful as
reference for: Google Maps JS integration patterns (`src/CommandMap.jsx`), NOAA weather
client (`src/weather.js`), timeline scrubber interaction
(`src/components/boards/TimelineBoard.jsx`). Its visual style (spy/ops aesthetic) is
explicitly what Kindred must NOT look like.
