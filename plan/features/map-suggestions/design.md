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
