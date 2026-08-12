# Kindred

A self-hosted, map-centric trip planner for groups of families.

Decide **where to go** (score polls), **what to do there** (map suggestions with voting
and comments), lock in **what we agreed** (admin-confirmed itinerary on a timeline with
weather), and see **where everyone is on the day** (check-ins and opt-in live location).
When it's over, the trip freezes into a browsable archive.

- **Stack:** FastAPI · PostgreSQL · React (Vite) PWA · Google Maps Platform · Docker Compose
- **Stages:** Planning → Holiday → End
- **Docs:** start at [`plan/overview.md`](plan/overview.md); contributors and AI agents read
  [`CLAUDE.md`](CLAUDE.md) first.

> Status: M0–M2 shipped — auth and onboarding, families (invites, roles, colours, privacy),
> admin console, polls and voting with live updates, the design system and chart library,
> and the M3 map groundwork (map shell, boundary/link-preview/distance services). Next:
> M3 map suggestions (needs Google Maps API keys), then itinerary, holiday mode, and
> notifications. The full written record lives in [`plan/`](plan/).

## Deploy

Three containers (Postgres, API, Caddy serving the built PWA), one `.env`, one command:

```bash
git clone https://github.com/jamatthes/Kindred.git
cd Kindred/deploy
cp .env.example .env   # then set SECRET_KEY, POSTGRES_PASSWORD, KINDRED_SITE_ADDRESS
docker compose -f docker-compose.yml up --build -d
```

Open the site and log in as `admin` / `admin`; you are forced to set a real password before
anything else. Full instructions — HTTPS, backups, upgrades — in
[`deploy/README.md`](deploy/README.md).

## Develop

- Server: `cd server && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"`,
  tests with `pytest` (needs a local Postgres and `TEST_DATABASE_URL`).
- Web: `cd web && npm install`, `npm run verify` (lint, token check, build, tests),
  `npm run e2e` (Playwright against a throwaway Docker stack). `npm run dev` runs against
  `FakeMapProvider` by default; drop a `web/.env.local` with `VITE_GOOGLE_MAPS_BROWSER_KEY=`
  set to enable the real map locally (gitignored — see `deploy/README.md`'s "Local
  development" section).
