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
- **Family admin** — one per family; manages own family's members, home address, and who in the family appears on the map.
- **Member** — individual login, belongs to one family; votes, suggests, comments, checks in, and alone decides whether to share their own location.

The first deploy seeds a platform account `admin`/`admin` and **forces a password change on first login**, after which the main admin names the trip before reaching the app.

**How people get in.** The main admin invites each family with a new-family invite link. The recipient registers, then names their family on a setup screen and becomes its family admin. From there a family admin invites their own family's members (or the main admin does it for them); a family admin can never invite into another family. Every account is created through an invite — there is no open sign-up.

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
| Who shows on the map | **Every sharing person individually** — one marker per person, never one per family. A marker requires all four of: family switch on, per-member switch on, the member's own toggle on, and a fresh position. The first three are permissions held by the family admin and can only ever *remove* a marker; **no API sets another user's consent** (added 2026-08-11; `families` FM-15, `holiday-stage` HS-15) |
| Family location policy | The family admin gets a family-wide switch, a per-member switch, and the default new members start at (off). Their own sharing starts on when they create the family. A seeded default is gated by the browser permission prompt **and** a one-time disclosure, so it pre-sets a toggle rather than granting consent (added 2026-08-11) |
| Identity | `users.first_name` + `users.last_name` alongside `display_name`, because the map badge is initials and its hover label is a full name — neither derivable reliably from one free-text field. Profile pictures via the existing `attachments` table, re-encoded server-side with **all EXIF including GPS stripped** (added 2026-08-11; `families` FM-14) |
| Onboarding | One server-owned gate: `auth/me.next_step` ∈ `change_password` / `setup_trip` / `setup_family` / `app`. The client routes on that field alone. The main admin names the trip on first login (`admin-console` AC-0); a new family's admin names their family on first login (`families` FM-13) — the family name is **not** collected on the join form (added 2026-08-11) |
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

**UI-first working style (added 2026-08-11):** the key screens are mocked as static,
token-pure pages in `design-preview/` (also pushed to the Claude Design project) *before*
their features are built. Feature UI work starts from the agreed mockup and may run against
mock data ahead of its backend endpoints; the backend for a feature is introduced when its
UI needs to persist or share state, per that feature's tasks.md ordering.

## Glossary

- **Suggestion** — anything proposed for the trip: a *region* (drawn area), *accommodation*, *activity*, or *meal*. Statuses: proposed → shortlisted → approved → scheduled.
- **Poll** — a structured group decision (score matrix or option vote), usually pre-map (which destination, how long, what vibe).
- **Check-in** — a single, deliberate location fix shared to the family map.
- **Stage** — Planning / Holiday / End; controls what actions are available.
