# Kindred — Overview

Kindred is a self-hosted, map-centric trip planning platform for groups of families.
It replaces ad-hoc spreadsheets and group chats with one place to decide **where to go**
(polls), **what to do there** (map suggestions + voting), **what we agreed**
(admin-confirmed itinerary + timeline), and **where everyone is on the day**
(check-ins / opt-in live location) — then freezes the trip into a browsable memory.

**System design inspiration:** Palantir Foundry Map / Maven — the map is the center of
the product; every dataset is viewable both as a table and as an overlay on the map;
detail lives in a right-hand side panel; time lives in a bottom timeline panel.
**Visual design is deliberately NOT Palantir:** friendly, light-first product styling
(see `design-system.md`). Palantir supplies the information architecture, not the look.

## Trip lifecycle

| Stage | What it means |
|---|---|
| **Planning** | Polls (destination/duration/interests scoring) AND map suggestions run in parallel — an open poll never blocks adding suggestions. Voting + comments on everything. Admin confirms what enters the itinerary. |
| **Holiday** | The trip is happening. Itinerary + map front and center; "now / next up" mobile view; check-ins and opt-in foreground live location. Suggestions still allowed, still admin-confirmed. |
| **End** | Everything frozen read-only. The trip becomes an archive/scrapbook (map + itinerary + photos + expenses). |

## Roles

- **Main admin** — one per platform/trip; also a regular family member. Final say: confirms/rejects suggestions into the itinerary, manages stages, configures voting modes, manages any family.
- **Family admin** — one per family; manages own family's members and home address.
- **Member** — individual login, belongs to one family; votes, suggests, comments, checks in.

The first deploy seeds a platform account `admin`/`admin` and **forces a password change on first login**.

## Decision log (settled 2026-08-10)

| Decision | Choice |
|---|---|
| Name | **Kindred** (was "palantir-for-family-trips") |
| Backend | **FastAPI** + SQLAlchemy 2 + Alembic + **PostgreSQL** (chosen over Flask: native async/WebSockets, Pydantic validation, auto OpenAPI docs) |
| Frontend | React + Vite, installable **PWA** |
| Maps | **Google Maps Platform** (JS Maps, Places, Distance Matrix, Geocoding, Directions) — free-tier viable at our scale IF cached server-side (see `architecture.md`); chosen over OSM stack for Places data + polish |
| API cost rule | Never call Google in a render path. Geocode homes once; Distance Matrix once per (home, suggestion) pair, cached in DB; Directions once per itinerary change, cached; Places re-fetched on card-open only (ToS: persist `place_id` only) |
| Accounts | Individual logins grouped into families; per-family admin; one main admin |
| Voting mode | Configurable **per poll / per suggestion category** (1–10 score or 👍/👎), set by admin |
| Trips scope | Single active trip in v1 UI; **schema multi-trip-ready** from day one |
| Theme | **Light by default**; dark mode = swapped token set; user preference persisted server-side |
| Notifications | In-app bell + unread counter + dropdown list (GitKraken-style) over WebSocket; Web Push via PWA (iOS requires add-to-home-screen); **email out of scope for v1** (schema allows later) |
| Location | Check-in button (single fix) + optional foreground `watchPosition` toggle, off by default, visible indicator. No background tracking (web platform can't; privacy feature anyway) |
| Deploy | Docker Compose on home server; **Cloudflare proxy in front of IPv6-only origin** (IPv4 reachability + auto-TLS; HTTPS is required by geolocation/PWA/push) |
| Charts | **Own small token-aware SVG chart widgets** — no heavy chart library; honesty rules baked in (see `design-system.md`) |
| Styling sources | Palantir = system design only. designmotionhq patterns = principles only, **explicitly do not copy its visual styling**. Visual direction set by a DesignSync pass after M0 |
| Docs-first | Every feature has `plan/features/<name>/{requirements,design,tasks}.md`, written before its code; docs updated when the feature changes |
| Legacy app | Stays at `E:\GitRepos\palantir-for-family-trips` as reference only (see `CLAUDE.md` for what it's good for) |

## Feature index

| # | Feature | One-liner |
|---|---|---|
| 1 | `foundation` | Monorepo scaffold, auth/sessions, seeded admin, Docker Compose, settings |
| 2 | `families` | Families, members, family admins, invites, home addresses |
| 3 | `admin-console` | Platform + trip configuration, voting-mode config, member management |
| 4 | `polls` | Score-matrix polls (the Excel replacement), live averages + disagreement, map overlay of results |
| 5 | `map-suggestions` | Regions/accommodation/activities/meals on the map; Places search prefill; popover card → side panel |
| 6 | `voting-comments` | Votes (per-category mode), comment threads, @mentions, admin confirm/reject, status flow |
| 7 | `distances` | Cached home→suggestion driving distances shown on cards |
| 8 | `itinerary-timeline` | Confirmed itinerary, bottom timeline scrubber, weather strip, cached routes |
| 9 | `holiday-stage` | Stage machine, check-ins, live location, now/next view, End freeze |
| 10 | `notifications` | In-app notification center over WebSocket |
| 11 | `pwa-push` | Installable PWA, Web Push, offline itinerary cache |
| 12 | `design-system` | Tokens, themes, chart widget library, shared UI primitives |

## Milestones

- **M0** — `foundation` scaffold + auth + Docker → then a **DesignSync pass** locks tokens/visual direction before any feature UI.
- **M1** — `families` + `admin-console` basics.
- **M2** — `polls` + map shell with poll-result tinting. **App becomes useful to the real family group here** (replaces the spreadsheet).
- **M3** — `map-suggestions` + `voting-comments` + `distances`.
- **M4** — `itinerary-timeline`.
- **M5** — `holiday-stage`.
- **M6** — `notifications` + `pwa-push`.
- **M7** — polish + End-stage archive view.

Each milestone executes its feature's `tasks.md` and ends with the verification steps listed there.

## Glossary

- **Suggestion** — anything proposed for the trip: a *region* (drawn area), *accommodation*, *activity*, or *meal*. Statuses: proposed → shortlisted → approved → scheduled.
- **Poll** — a structured group decision (score matrix or option vote), usually pre-map (which destination, how long, what vibe).
- **Check-in** — a single, deliberate location fix shared to the family map.
- **Stage** — Planning / Holiday / End; controls what actions are available.
