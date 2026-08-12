# map-suggestions — Design

Implements `requirements.md` in this directory. Read `plan/architecture.md` (schema, API
conventions, Google cost rules) and `plan/design-system.md` (layout, tokens, patterns) first.

> **NOTE (pre-build, branch `feat/m3-services`):** the two standalone external-service modules
> this feature needs — `server/app/services/link_preview.py` (SSRF-guarded fetch, OG +
> Airbnb-aware parsing, in-memory LRU/TTL cache) and `server/app/services/boundaries.py`
> (Nominatim boundary lookup, hand-implemented Douglas-Peucker simplification, ellipse
> fallback) — are already implemented and unit-tested on that branch, ahead of this feature's
> own Phase 4/5 work. Both are route-free: no router, no schema change, nothing wired into
> `app.main`. The M3 implementer should merge/cherry-pick that branch (or re-review and adapt
> its two files) rather than writing these from scratch, then wire
> `get_link_preview_service()` and `get_boundary_service()` into the `POST /link-preview` and
> region-creation routes per the contracts documented inline in each module. Tests:
> `server/tests/test_link_preview.py`, `server/tests/test_boundaries.py`, fixtures under
> `server/tests/fixtures/`.

> **NOTE (pre-build, branch `feat/m3-map-shell`):** the provider-agnostic map shell —
> components only, no screen/route — is pre-built on that branch, ahead of this feature's own
> UI phases: `web/src/features/map/`. It gives the M3 implementer tested UI to inherit rather
> than building it inline. Contents:
> - `MapProvider.ts` — the provider interface (`mount`/`unmount`, `setCenter`/`panTo`/
>   `setZoom`/`fitBounds`/`getViewState`, `addMarker`/`updateMarker`/`removeMarker`,
>   `addPolygon`/`updatePolygon`/`removePolygon`, and a typed `on(event, handler)` for
>   `markerClick` / `markerHover` / `polygonClick` / `mapClick`). Imperative by design —
>   matching how every real map SDK (Google included) actually works — with `MapCanvas` as
>   the declarative React layer on top that diffs `markers`/`polygons` props against calls.
> - `FakeMapProvider.ts` — deterministic, DOM-based, used by every test and the styleguide.
>   Positions come from a genuine linear lat/lng→pixel projection (`projection.ts`, not a
>   real Mercator basemap — it says so in its own doc comment), and markers/polygons are
>   real DOM/SVG nodes, not mocked calls.
> - `GoogleMapProvider.ts` — a STUB. Every method throws "not wired yet" — no script tag, no
>   dependency added, no network call. **The M3 implementer's job is to replace this one
>   file** with the real Google Maps JS integration (needs the user's browser-restricted API
>   key, not yet configured); nothing else in the feature should need to change, because
>   `MapCanvas` and every pin/polygon/popover component only ever talk to `MapProvider`.
> - `SuggestionPin.tsx` / `LiveMarker.tsx` / `RegionPolygon.tsx` / `PopoverCard.tsx` — the
>   three progressive-disclosure level-1/2 components from "Map layer specifics" /
>   "Progressive disclosure" above. `LiveMarker` reuses `IdentityBadge`
>   (`plan/features/families/design.md`) rather than reinventing a person marker.
>   `PopoverCard`'s vote-summary and distance-chip areas are slots (`ReactNode`), not
>   hardcoded shapes — their real content belongs to `voting-comments` and `distances`.
> - `prefTint.ts` reuses `charts/scales.ts`'s `prefRampStep` so a region's map tint and its
>   `HeatMatrix` cell agree on which ramp step a given score rounds to.
> - Styleguide: a "Map shell" section in `/styleguide` (`web/src/charts/StyleguideMap.tsx`)
>   showing `FakeMapProvider` with sample pins of every category/status, the preference
>   ramp across region tints, and the popover card, in both themes.
> - Tests: 149 Vitest cases across the feature (`web/src/features/map/*.test.{ts,tsx}`) —
>   projection math (including a round-trip property), provider interface conformance,
>   marker/polygon lifecycle and event dispatch, `MapCanvas`'s prop-diffing, and every
>   component's render/interaction states.
>
> **Deviations from this doc, and why:**
> - **Clustering is not built.** "Map layer specifics" above specifies pin clustering; this
>   pre-build is components-only with no live suggestion list to cluster against, and
>   cluster composition logic (count + "mixed cluster" hint) is presentation logic over real
>   data the M3 screen owns, not a provider-shell concern. `MapProvider` does not need to
>   change to add it — a cluster is just another marker-like DOM node the screen computes.
> - **"Open in Google Maps" deep-link construction is not built.** `PopoverCard` exposes an
>   `onOpenInMaps` slot (renders the button only when supplied) rather than building the
>   `https://www.google.com/maps/...` URL itself, because that needs `place_id`/region-vs-
>   point branching that belongs to the screen wiring the card to real suggestion data.
> - **OSM attribution text is not baked into `RegionPolygon`.** The component exposes
>   `boundarySource` as a `data-boundary-source` attribute so a consumer can render the
>   required "boundary © OpenStreetMap contributors" line appropriately positioned for its
>   own layout (the styleguide demo does this as a single map-level caption, not per-region,
>   which is also the expected real-screen pattern per the reference mockup).
> - **Sequence numbers for `scheduled` pins are not implemented.** The design doc says a
>   scheduled pin "carries a sequence affordance"; `SuggestionMarkerSpec` has no itinerary
>   day-order field to draw one from (that belongs to `itinerary-timeline`), so
>   `SuggestionPin` currently renders scheduled status with a distinct glyph (▸) and colour,
>   satisfying "never colour alone" without inventing itinerary data it doesn't have. The M3
>   implementer can extend the glyph to a numbered badge once a sequence value exists.

> **NOTE (server build, branch `feat/m3-suggestions-server`):** Phases 1-6 and 11b of
> `tasks.md` are implemented — migration, models, schemas, service layer, router, server tests,
> and the poll-decision → region hand-off. Phases 7-11 (web) and 12 (docs/ops handoff) are not.
> Files: `server/app/models/suggestion.py`, `server/app/models/geo.py`,
> `server/app/schemas/suggestion.py`, `server/app/services/suggestions.py`,
> `server/app/routers/suggestions.py`, `deps.require_can_edit_suggestion`, plus the
> `suggestions` table and the deferred `poll_options.suggestion_id` FK in
> `alembic/versions/0001_schema.py`. Tests: `test_models_suggestion.py`,
> `test_schemas_suggestion.py`, `test_service_suggestions.py`, `test_router_suggestions.py`,
> `test_seed_region.py` (145 cases).
>
> **Deviations from this doc, and why:**
> - **The polygon vertex cap is 500, not 200.** This document names both numbers — "≤ 500
>   points" for simplified OSM boundaries, and "a vertex-count cap (target 200)" in the
>   edge-case table. They cannot both govern one validator: 200 would reject the very
>   boundaries the doc instructs the server to fetch and store, since
>   `services/boundaries.py` simplifies to `MAX_RING_POINTS = 500`. The larger number wins and
>   the two constants now agree (`schemas/suggestion.py`, `MAX_POLYGON_POINTS`).
> - **`vote_summary` and `distances` ship as honest zeros.** `suggestion_votes` belongs to
>   `voting-comments` and `distance_cache` to `distances` — sibling M3 features, neither
>   table created yet. `SuggestionOut` carries both fields in their documented shape, filled
>   with a zero tally and an empty list, rather than omitting them: the wire contract does not
>   change when those features land, and the web agent can build the card against the real
>   shape today. Marked `NOTE (voting-comments)` / `NOTE (distances)` at both sites.
> - **`sort=votes_*` and `sort=distance_*` are accepted and currently order by creation**, for
>   the same reason — the columns they sort on do not exist yet. Accepted rather than rejected
>   so the sort control the web agent is building has a stable contract; a `422` on a control
>   the user can see is the worse failure. `sort=category_*` and `created_*` are real.
> - **`DELETE` checks `status = 'scheduled'` only, and does not name the itinerary day.**
>   `itinerary_items` arrives with `itinerary-timeline` (M4). The `409` and its code are final;
>   M4 adds the row lookup and the day to the message.
> - **Named-locality regions are created through a `boundary_query` field on
>   `POST /suggestions`**, not a separate lookup endpoint. This doc specifies the behaviour
>   ("one server-side fetch at region creation") but not the wire shape; one create route with
>   an alternative seed keeps every creation flow converging on one endpoint, as the four UI
>   entry points already do. Nominatim finding nothing is `404 boundary_not_found`; finding a
>   place but no boundary stores the fitted ellipse, `properties.boundary_source =
>   "fallback_ellipse"`, which the UI marks approximate. `boundary_source` is lifted to a
>   top-level `SuggestionOut` field so the ODbL attribution has one thing to key off.
> - **`SuggestionCreate` forbids unknown fields**, so an inflated payload carrying Google's
>   photos or rating is a `422` rather than being silently trimmed. The HARD INVARIANT is
>   thereby enforced at the edge as well as by the absence of columns, and a client sending
>   Places details is told to stop rather than left thinking it worked.
> - **Capability flags added to `SuggestionOut`** (`can_edit`, `can_delete`,
>   `can_change_status`), matching `schemas/poll.py`'s rule that the frontend renders
>   permission and never derives it. They are computed from the same predicate
>   `require_can_edit_suggestion` enforces, so the button and the route cannot disagree.
> - **`seed_region` refuses a non-geographic option with `422 option_not_located`**, where the
>   M2 shell returned `409`. `tasks.md` Phase 11b asks for `422`, and it is the better answer:
>   the request is well-formed and the poll is in the right state; the option is what cannot be
>   honoured.
> - **`PATCH /{id}/status` treats re-sending the current status as a no-op**, not an invalid
>   transition. Two organisers pressing "shortlist" at once should not produce an error for
>   whichever lost.
> - **`queue_distance_recompute` is a placed no-op.** The create path and the move path both
>   call it, and the epsilon behaviour is tested through it (5 m does not reach it, 500 m
>   does), so `distances` has one function to fill in rather than two call sites to find.
> - **`Suggestion` declares one relationship, `author`, not the four `tasks.md` Phase 2 lists.**
>   `trip` is unused — every read is already trip-scoped through a `WHERE`, and an eager
>   relationship would fetch the trip row once per suggestion for nothing. `suggestion_votes`
>   has no table yet. `comments` is polymorphic and *cannot* carry a relationship: it has no FK
>   to its subject, which is the documented cost of one thread implementation serving three
>   subjects — the count comes from a grouped query in `services/suggestions.py` and the delete
>   cascade is the router's, in the same transaction, exactly as `polls` does it.
> - **Implementation note, not a deviation:** `geometry_geojson` and `place_snapshot_json` are
>   `JSONB(none_as_null=True)`. Without it SQLAlchemy writes a Python `None` as the JSON value
>   `null`, which is not SQL NULL — and `ck_suggestions_geometry_iff_region` would then reject
>   every non-region row ever inserted.

---

## HARD INVARIANT — Google Places and the Terms of Service

**This section governs every decision below. Breaking it is a licensing violation, not a bug.**

Google's Places Terms of Service forbid persisting Place Details content. Kindred therefore:

1. **Persists exactly one Google-derived value: `place_id`.** It is stored in
   `suggestions.place_id`. That identifier is explicitly permitted to be cached indefinitely.
2. **Persists user-authored fields only** in `suggestions.title`, `suggestions.notes`, and
   `suggestions.place_snapshot_json`. `place_snapshot_json` holds the name and address *as the
   user accepted or edited them in the create form* — it is a record of what the human typed,
   not a copy of Google's response. It exists so the card renders something sensible when
   Places is unavailable.
3. **Never writes to the database**: photos or photo references, ratings, review counts,
   review text, opening hours, phone numbers, website URLs sourced from Google, editorial
   summaries, price level, or business status.
4. **Re-fetches details live on card-open.** When a user opens a suggestion's side panel and
   the record has a `place_id`, the browser calls Places Details and renders photos/hours/
   rating from that live response. The response is held in an in-memory client cache with a
   short TTL (target 5 minutes, cleared on reload) purely to avoid re-billing a rapid
   reopen. It is never sent to the server for storage.
5. **Latitude/longitude are ours to keep.** The user chose the location; coordinates are
   treated as user-authored geometry, consistent with `architecture.md` storing `lat`/`lng`.

Implementation consequence: there is no server endpoint that returns Google place details.
Details flow browser → Google → browser only. The server never proxies them.

---

## Data model

All tables and columns below already exist in `plan/architecture.md`. No schema changes are
required for this feature.

### `suggestions` (used as-is)

| Column | Use here |
|---|---|
| `id` | uuid pk |
| `trip_id` | trip scope — always filtered on; never assume a single trip |
| `type` | `region` / `accommodation` / `activity` / `meal` — drives pin icon and grouping |
| `title` | user-authored display name |
| `notes` | free text from the author |
| `status` | `proposed` / `shortlisted` / `approved` / `scheduled` / `rejected` |
| `created_by` | author user id; their family supplies the pin colour accent |
| `lat` / `lng` | pin position. For regions this is the **centroid** of the geometry |
| `geometry_geojson` | regions only — see encoding below |
| `place_id` | nullable; Google place identifier, the only Google value persisted |
| `place_snapshot_json` | user-authored name/address as entered — never Google's details |
| `created_at` / `updated_at` | standard |

### Region geometry encoding

`geometry_geojson` stores a GeoJSON `Feature`. Two shapes are supported.

**Circle** — GeoJSON has no circle primitive, so a circle is a `Point` carrying a radius in
`properties`:

```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [-4.7, 50.4] },
  "properties": { "shape": "circle", "radius_m": 12000 }
}
```

**Polygon** — a standard closed ring, first and last coordinate identical:

```json
{
  "type": "Feature",
  "geometry": { "type": "Polygon", "coordinates": [[[-4.8,50.3],[-4.6,50.3],[-4.6,50.5],[-4.8,50.3]]] },
  "properties": { "shape": "polygon" }
}
```

Rules:
- `properties.shape` is required and is the discriminator the renderer switches on.
- Coordinates are `[lng, lat]` — GeoJSON order, the reverse of Google's `LatLng`. The
  conversion happens once in the map wrapper; the API speaks GeoJSON order throughout.
- `suggestions.lat`/`lng` are always populated for regions with the centroid: the circle's
  centre, or the polygon's vertex-average. This keeps regions sortable, selectable, and
  distance-computable with no special-casing anywhere else in the system.
- Validation: polygon needs ≥ 4 positions (closed triangle minimum); `radius_m` must be
  positive and is clamped to a sane maximum (target 200 km) to prevent a whole-globe circle.
- Non-region types must have `geometry_geojson` null; regions must have it non-null.
- **Polygon is the primary shape** (user directive 2026-08-11): regions should read like
  Google Maps' own locality boundaries — an organic outlined area, not a circle. The draw
  tool defaults to freehand/click-to-place polygon outlining; circle remains only as a
  quick-draw convenience, and both render identically as a dashed outline with a tinted
  fill (preference-ramp tint when poll/vote scores exist, neutral otherwise). Reference
  rendering: `design-preview/screen-planning-map.html`.

### Named-locality regions (decision 2026-08-11)

When a region is created by searching a named place ("Hampshire", "Cornwall") rather than
drawing, we want the real administrative boundary — the dashed outline Google shows for a
locality — with our tinted fill. Google's APIs never return that polygon (their boundary
data is render-only and licensed), so:

- **Boundary source: OpenStreetMap via Nominatim** (`polygon_geojson=1`). One server-side
  fetch at region creation; the returned boundary GeoJSON is stored in
  `geometry_geojson` (`properties.shape: "polygon"`, plus `properties.boundary_source:
  "osm"` and the OSM relation id) and cached forever — never re-fetched on render, per the
  API-cost rule. ODbL requires a visible "boundary © OpenStreetMap contributors"
  attribution wherever such a region renders.
- Downstream, a named-locality region is an **ordinary region row**: same rendering path
  (dashed outline + tint), same centroid for distances, works in exports and the End-stage
  archive, and permits exact point-in-region math later. No Google feature-layer / Map ID
  dependency (that approach is explicitly rejected: render-only, own SKU, no stored
  geometry).
- Simplify oversized rings server-side (Douglas–Peucker to a sane vertex budget, target
  ≤ 500 points) before storing; UK county boundaries at full OSM resolution are far
  denser than a map overlay needs.
- **Fallback** when Nominatim has no boundary for the query: seed a rounded ellipse
  fitted inside the geocoded bounding box, visually labelled approximate, with a
  "refine the outline" action opening the draw tool pre-seeded with that shape. Never
  render a raw bounding-box rectangle.
- Nominatim usage policy: single fetch per created region with proper User-Agent
  identification; tests fake the service, as with every external call.

### Grouping (derived, never stored)

Activities and meals that sit at an accommodation are grouped at query time. No column, no
join table.

A suggestion `C` is a child of accommodation `A` when all hold:
1. `A.type = 'accommodation'` and `C.type` is `activity` or `meal`;
2. same `trip_id`;
3. either `A.place_id` and `C.place_id` are both non-null and equal, **or** the haversine
   distance between their points is below the proximity threshold (target 150 m);
4. `C` is not already a child of a nearer accommodation — ties resolve to the closest, then
   to the oldest `created_at`.

The list endpoint returns children nested under their parent and omits them from the top
level; the map still renders every child pin, offset so overlapping pins remain clickable.
Because grouping is derived, moving a pin re-groups automatically with no migration.

---

## REST endpoints

All under `/api/v1`, Pydantic schemas both directions, session cookie auth, CSRF token on
mutations. Permission dependencies named per `architecture.md`.

### `GET /api/v1/suggestions`
List for a trip. The single source for both map and list views.

Query: `trip_id` (required), `type[]`, `status[]`, `family_id[]`, `sort`
(`votes` / `distance` / `category` / `created`, each `_asc` or `_desc`), `group` (bool,
default true), `include_rejected` (bool, default false).

Response — each item:
```
id, type, title, notes, status, created_by { user_id, display_name, family_id, family_color },
lat, lng, geometry_geojson, place_id, place_snapshot { name, address },
external_url, vote_summary { mode, count, average|up|down, my_vote },
comment_count, distances [ { family_id, family_name, duration_s, distance_m, is_estimate } ],
children [ ...same shape, one level only ], created_at, updated_at
```
Permission: `require_member`. Distance and vote data are denormalised into this response so
the list renders in one request — see `distances` and `voting-comments` for their origin.

### `POST /api/v1/suggestions`
Request: `trip_id, type, title, notes?, lat, lng, geometry_geojson?, place_id?,
place_snapshot?, external_url?`
Response: the created suggestion.
Permission: `require_member` + `require_stage("planning", "holiday")`.
Side effects: emits `suggestion.created`; schedules the background distance task
(`distances` feature) for the new pin against every geocoded family home.
Validation: geometry required iff `type = region`; `lat`/`lng` required always; the server
recomputes and overwrites the centroid for regions rather than trusting the client.

### `GET /api/v1/suggestions/{id}`
Single record, same shape as the list item plus the full comment thread.
Permission: `require_member`.
Note: contains no Google details — the browser fetches those itself.

### `PATCH /api/v1/suggestions/{id}`
Request: any of `title, notes, type, external_url, lat, lng, geometry_geojson, place_id,
place_snapshot`.
Permission: `require_member`, plus ownership — author, or family admin of the author's
family, or main admin. Enforced in a `require_can_edit_suggestion(id)` dependency.
Stage: `require_stage("planning", "holiday")`.
Side effects: emits `suggestion.updated`; if the point moved beyond a small epsilon
(target 25 m) it also emits `suggestion.moved` and re-queues the distance task. Status is
**not** patchable here.

### `DELETE /api/v1/suggestions/{id}`
Permission: same ownership rule as PATCH. Stage: planning/holiday.
Rejects with `409 Conflict` when the suggestion has `status = 'scheduled'` or any
`itinerary_items` row references it, with a message naming the itinerary day.
Cascades: `suggestion_votes` and `comments` for the subject are removed;
`distance_cache` rows for the pair are removed.
Emits `suggestion.deleted`.

### `PATCH /api/v1/suggestions/{id}/status`
Request: `status` (`shortlisted` / `approved` / `rejected` / `proposed`).
Permission: `require_main_admin`. Stage: planning/holiday.
Allowed transitions are validated server-side:
`proposed → shortlisted | approved | rejected`,
`shortlisted → approved | rejected | proposed`,
`approved → shortlisted | rejected | proposed`,
`rejected → proposed`.
`scheduled` is rejected here with `422` — only the itinerary feature sets it.
Emits `suggestion.status_changed`. The UI controls live in `voting-comments`.

### `POST /api/v1/link-preview`
Request: `url`.
Response `200`: `{ title?, description?, image_url?, site_name? }`.
Response `204`: no preview available — the normal outcome for sites that block scraping.
Permission: `require_member`. Stage: planning/holiday.
Behaviour: server-side fetch with a short timeout (target 4 s), a size cap (target 512 KB),
redirect limit, and http/https-only scheme check. Parses OpenGraph then plain `<title>`.
Results are held in an in-memory LRU with a short TTL; **nothing is persisted**.
NOTE: a `link_preview_cache` table is deliberately not part of v1. It is a reasonable later
addition if scrape latency becomes noticeable.

**Airbnb-aware extraction** (verified against a live listing from a residential IP,
2026-08-11 — HTTP 200, no bot-block): two layers with different reliability contracts.
- *OG contract (stable — these tags exist for link previews):* `og:title` carries
  structured facts ("Home in Dent · ★4.8 · 5 bedrooms · 7 beds · 4.5 bathrooms"),
  `og:description` the listing name, `og:image` a 720px hero photo, and the `<title>` tag
  the locality ("Dent, England, United Kingdom"). Parse the rating/bedroom/bath facts out
  of `og:title` when present; response gains optional fields `facts`, `locality`.
- *Best-effort bonus (embedded page JSON — may break on any Airbnb redesign, degrade
  silently):* approximate coordinates (`"latitude"/"longitude"` — Airbnb's own fuzzed
  location, so the pin can pre-drop itself) and `personCapacity` (sleeps). Response gains
  optional `lat`, `lng`, `capacity`. When absent the create flow simply asks the user to
  drop the pin, exactly as before — no error surfaced.
- *Never available:* price (rendered client-side from their API) and the full gallery —
  price stays a typed field; gallery photos come from user-uploaded attachments.
Security: the fetch must refuse private/loopback/link-local address ranges after DNS
resolution (SSRF guard) — this endpoint takes a user-supplied URL.

### `POST /api/v1/polls/{id}/decision/seed-region` (owned by `polls`, implemented here)
The `polls` feature ships this route at M2 returning `501 not_available`; this feature
replaces it with the real implementation at M3 and adds the deferred FK
`poll_options.suggestion_id → suggestions.id` (`ON DELETE SET NULL`). Creates an idempotent
`region` suggestion from a decided geographic poll option and writes its id back to the
option. Permission: `require_main_admin`. Stage: planning/holiday. Full contract in
`plan/features/polls/design.md`; implementation steps in this feature's `tasks.md`
(Phase 11b).

---

## WebSocket events

One socket per session, trip-scoped rooms, per `architecture.md`.

### Emitted by this feature
| Event | Payload | When |
|---|---|---|
| `suggestion.created` | full suggestion object | POST succeeds |
| `suggestion.updated` | full suggestion object | PATCH succeeds |
| `suggestion.moved` | `id, lat, lng, geometry_geojson` | point moved > epsilon |
| `suggestion.status_changed` | `id, status, changed_by` | status PATCH succeeds |
| `suggestion.deleted` | `id` | DELETE succeeds |

### Consumed by this feature
| Event | Effect |
|---|---|
| `suggestion.vote.updated` | update the tally on the card, popover, and list row |
| `distance.updated` | swap an estimate chip for the real value |
| `comment.created` / `comment.deleted` | adjust the comment count badge |
| `stage.changed` | re-evaluate whether create/edit affordances render |

Own actions apply optimistically and roll back if the socket reports an error, per
`design-system.md`. The echo of one's own event is idempotent — reconcile by `id`.

---

## UI behaviour

### Layout
Desktop follows the 62/38 split from `design-system.md`: slim left nav rail, map at ~62%,
right side panel at ~38%, collapsible bottom timeline panel (owned by `itinerary-timeline`).
Mobile: full-bleed map, bottom tab nav, cards as bottom sheets for thumb reach.

The list view is not a separate route. On desktop it occupies the side panel when nothing is
selected, and is reachable as a "List" toggle when something is. On mobile it is a sheet
raised from the bottom tab bar. Map and list always reflect the same filter and selection
state — one store, two renderers.

### Progressive disclosure — the three levels
Per `design-system.md`, detail escalates and never skips a level.

1. **Pin / overlay.** Type icon, family colour accent, status treatment (proposed = default,
   shortlisted = emphasised, approved = strongest, rejected = muted/desaturated,
   scheduled = carries a sequence affordance). Status is never carried by colour alone — the
   icon or a glyph differs too.
2. **Popover card** (map click). Title, type, vote tally widget, comment count, distance
   chips, and a "Details" action. Compact and glanceable; no scrolling.
3. **Side panel / bottom sheet** ("Details"). Full record: photo strip, notes, external
   link, all families' distances, grouped children, comment thread, admin controls. This is
   where the heavy lifting happens.

**Photo-source tiering** — the photo strip resolves from the first non-empty tier:
1. live Google Place Details photos (when the suggestion has a `place_id`);
2. user-uploaded `attachments` (the norm for Airbnbs — family members screenshot the
   listing's best photos and drop them on the suggestion);
3. the link preview's `og:image` hero (hot-linked, never copied to our storage);
4. designed placeholder. Tiers never mix in one strip; upload always available regardless
   of tier.

Both the popover card and the details view carry an **"Open in Google Maps" action**
(prominent on mobile, secondary on desktop): a universal Maps deep link —
`https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>` plus
`&destination_place_id=<place_id>` when one is stored — which opens the native Google Maps
app on phones for turn-by-turn navigation. This is a plain URL, not an API call: no key, no
quota, ToS-fine. Region suggestions use
`https://www.google.com/maps/search/?api=1&query=<lat>,<lng>` instead (an area to look at,
not a navigation destination).

### Map layer specifics
- **Clustering** for pins. Clusters show a count and a composition hint so a cluster of
  restaurants reads differently from a mixed cluster. Regions never cluster.
- **Z-order**: region fills at the bottom, then route lines (itinerary feature), then pins,
  then the selected pin raised above all.
- **Selection sync**: selecting anywhere pans/zooms the map only if the target is off-screen;
  it never re-centres gratuitously while the user is panning.
- **Grouped children** render offset on a small radial arrangement around the parent so each
  stays independently clickable; the group draws a faint connector to its parent.
- **Photo strip** appears only after the live Places Details call resolves; before that it is
  a skeleton, and on failure it is simply absent (no error chrome for a missing photo).

### Creation flows
All four entry points converge on one create form; they differ only in how the form is seeded.

- **Search** — Autocomplete field → prediction → browser Place Details → seeds title,
  address, coordinates. The user edits freely. Only what is in the form at save time is sent.
- **Drop pin** — cursor changes, one map click places a draggable provisional pin, form opens
  with coordinates only.
- **Draw region** — circle or polygon tool; shape adjustable pre-save; type locked to
  `region`; the centroid is displayed so the user sees where the "pin" will sit.
- **Paste URL** — URL field triggers the best-effort `POST /link-preview`; on `200` the title
  pre-fills (still editable), on `204` nothing happens and no error shows. Location still
  comes from search or a dropped pin.

Form states: all six field states styled from day one; validate on blur, re-validate on
change after the first error; error text sits beneath the field, never colour alone.

### List/table specifics
Tri-state sort (asc → desc → original) per `design-system.md`, sticky header, tabular figures
with right-aligned numerics, full-row click targets, density from spacing tokens. Filter
chips for type, status, and family sit above the table and are shared with the map.

### Styling
Token-only. Pin size, cluster size, offsets, and region fill opacity are component tokens
(`--pin-size`, `--region-fill-opacity`, …). Family colours come from the `--family-1…8`
semantic slots via `families.color`. Both light and dark must be checked — region fills and
cluster badges are the two places where a naive dark inversion looks wrong.

### Motion
150–250 ms, standard easing: pin drop on create, card in on selection, sheet up on mobile.
`prefers-reduced-motion` removes the pin-drop and sheet transitions. Nothing decorative.

### Empty and loading states
- No suggestions: "No suggestions yet — drop the first pin", with the create action inline.
- Filters exclude everything: "No suggestions match these filters", with a clear-filters action.
- Structural loads (map panel, list) use skeletons; sub-second inline waits use spinners.

---

## Edge cases and error states

| Case | Handling |
|---|---|
| Google Maps JS fails to load / key missing | Map area shows an explanatory empty state; the list view remains fully functional so the trip is still usable. Never a blank screen. |
| Places Autocomplete quota exhausted or errors | Search field shows an inline notice and the flow falls back to "drop a pin instead", which needs no Google call beyond the basemap. |
| Place Details fails on card-open | Photo strip and live fields are omitted; the panel renders from `place_snapshot_json` and user-authored fields. No blocking error. |
| Suggestion has no `lat`/`lng` | Not possible — coordinates are required at creation. Any legacy row lacking them is listed but not mapped, with a "no location" affordance. |
| Region saved with invalid geometry | `422` with a field-level message; the drawing stays on screen for correction rather than being discarded. |
| Two suggestions share a `place_id` | Allowed and expected (an accommodation plus a meal at the same hotel). Grouping handles the display; no uniqueness constraint. |
| Duplicate accommodation at the same `place_id` | Allowed, but the create form warns "Someone already suggested this place" with a link to the existing one before saving. |
| Delete a scheduled suggestion | `409` naming the itinerary day; the UI offers a deep link to the itinerary item. |
| Concurrent edit (two users patch the same record) | Last write wins on a per-field basis; the WS `suggestion.updated` echo reconciles both clients. No locking in v1. |
| Status change races a delete | Whichever commits first wins; the loser receives `404` and the client removes the record on `suggestion.deleted`. |
| Pin dragged a trivial distance | Below the 25 m epsilon no distance recompute is queued — this protects the Distance Matrix budget from jitter. |
| Link preview times out or is blocked | `204`; silent. The user types the title. |
| Link preview URL resolves to a private address | Rejected before fetch (SSRF guard); returns `204` so the UI treats it as "no preview". |
| WebSocket disconnected | Client refetches the suggestion list on reconnect and reconciles by `id`; optimistic edits that were never acknowledged roll back visibly. |
| End stage reached mid-edit | The stage guard rejects the save with `403`; the client shows the trip-is-frozen state and switches to read-only chrome. |
| Very large polygon or a runaway circle | `radius_m` clamp and a vertex-count cap (target 200) reject the shape with a message rather than storing something unrenderable. |

---

## NOTE (2026-08-12) — M3 web implementation, deviations from this doc

Built in `web/src/features/map-suggestions/` (data layer, creation flows, list/filters,
detail panel) on top of the pre-built `web/src/features/map/` shell, against mock/typed
fixtures — no backend exists in this worktree (a separate agent builds `server/` on a
different branch/worktree in parallel). Full detail and reasoning live inline in
`tasks.md` Phases 7–11 next to each checklist item; summarised here per the docs-first rule:

- **No standalone anchored popover on desktop.** Pin click goes straight to the full
  `SuggestionDetailPanel` rather than a floating card positioned over the pin, because
  `MapProvider` exposes no live marker screen-position query to anchor one against. Mobile
  *does* get the real two-level disclosure (`BottomSheet`'s peek/full snaps). See
  `tasks.md` Phase 8.
- **Clustering is a coarse lat/lng grid, not pixel-distance.** Same root cause: no
  projection query on a mounted provider outside `FakeMapProvider`'s test-only accessors.
- **Provisional-pin dragging and freehand polygon drawing are click-based, not
  drag-based.** `MapProvider`'s event surface is `markerClick`/`markerHover`/
  `polygonClick`/`mapClick` only — no drag events. Click-to-reposition and
  click-to-place-vertex reach the same outcomes; the latter is explicitly one of this
  doc's own two sanctioned draw modes already.
- **Selection does not check "is the target off-screen" before panning.** `MapProvider` has
  no viewport-bounds query; the screen recentres on every selection instead.
- **`GoogleMapProvider` is now a real implementation, not the stub**, replacing it per this
  doc's own instruction — but it is unexercised by any test or dev run here, since
  `VITE_GOOGLE_MAPS_BROWSER_KEY` is not configured anywhere yet. Flag it for a manual smoke
  pass once a browser key is provisioned (Phase 12's Cloud Console checklist).
- **The Airbnb preview's `capacity` field has nowhere to land.** `suggestions` has no
  "sleeps" column; the type carries it but the create form does not surface it as its own
  field. Worth a schema conversation if the sleeps count turns out to matter in practice.
- **Explicit new motion (150–250 ms pin-drop/card-in/sheet-up) was not authored.** Existing
  `BottomSheet` transitions and reduced-motion handling are reused as-is; a dedicated polish
  pass is still owed.

All four deviation-causing gaps in `MapProvider` (marker screen-position, drag events,
viewport-bounds query) are additive and backward-compatible — extending the interface later
does not require revisiting any of the components built in this phase, which is why they
were left as follow-ups rather than blocking this phase on a provider-layer change the
brief said to avoid absent a genuine requirement.
