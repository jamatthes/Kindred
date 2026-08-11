# itinerary-timeline — Design

Implements `requirements.md` in this directory. Read `plan/architecture.md` (schema, Google
cost rules, weather providers) and `plan/design-system.md` (bottom panel for time, 62/38 split,
deferred drag-and-drop) first.

---

## Data model

### `itinerary_items` (exists in `architecture.md`, used as-is)

| Column | Use here |
|---|---|
| `id` | uuid pk |
| `trip_id` | trip scope — always filtered on |
| `suggestion_id` | nullable; null for admin-added items with no suggestion behind them |
| `day` | date; must fall within the trip's `start_date`…`end_date` |
| `start_time` | nullable time; null means "sometime this day" |
| `end_time` | nullable time |
| `title` | override; when null, the linked suggestion's title is used |
| `confirmed_by` | the admin who scheduled it |
| `sort` | integer ordering within a day |
| `created_at` / `updated_at` | standard |

Ordering within a day: items with a `start_time` sort by it; items without sort by `sort` and
render in a separate unscheduled band. `sort` is a sparse integer (steps of 100) so a single
reorder rewrites one row rather than renumbering the day.

Location comes from the linked suggestion's `lat`/`lng`. An item with no `suggestion_id` has no
location, and therefore no pin and no route leg. NOTE: this means an admin-added item cannot be
mapped in v1. Giving `itinerary_items` its own coordinates was considered and rejected as
duplicate geometry — if a bare item needs a location, the admin creates a suggestion for it and
approves their own suggestion, which is one extra step and keeps one source of truth for points.

### `route_cache` (exists, used as-is)

| Column | Use here |
|---|---|
| `id` | uuid pk |
| `trip_id` | trip scope |
| `from_lat` / `from_lng` | origin of the leg |
| `to_lat` / `to_lng` | destination of the leg |
| `polyline` | encoded polyline for drawing |
| `duration_s` / `distance_m` | leg totals, shown between items on the day view |
| `provider` | `google` |
| `computed_at` | when it was fetched |

**Legs are looked up by coordinates, not by a foreign key to items.** A leg is identified by its
rounded `(from_lat, from_lng, to_lat, to_lng)` tuple. Rationale: the same drive recurs across
days and across itinerary edits — a cache keyed by geometry is reused, while a cache keyed by
item ids would be thrown away every time the admin reorders. Coordinates are rounded to a fixed
precision (target 5 decimal places, ~1 m) before lookup and storage so floating-point noise
cannot cause a miss.

NOTE: `itinerary_items.kind` (`item`/`travel`/`note`) was considered so travel could be a
first-class timeline row, and deliberately skipped for v1. Travel renders as a derived segment
between consecutive items. It remains a clean future addition.

Invalidation: on any itinerary change, recompute the set of required legs for the affected days,
fetch the missing ones, and delete `route_cache` rows for this trip that no longer correspond to
any required leg. Rows are never expired by age — a road between two fixed points does not
change meaningfully on a trip-planning timescale.

### `weather_cache` (exists, used as-is)

| Column | Use here |
|---|---|
| `id` | uuid pk |
| `lat` / `lng` | **rounded grid key**, not the exact point |
| `date` | the forecast day |
| `payload_json` | normalised forecast payload (see below) |
| `fetched_at` | drives the ~1h TTL |

The grid key rounds coordinates (target 2 decimal places, ~1 km) so several suggestions in the
same town share one cache entry. Weather does not vary meaningfully across a village.

### `trips` (read here, written by `admin-console`)

`start_date`, `end_date`, and `timezone` define the timeline's extent and the day boundaries.
All day arithmetic uses `trips.timezone` — never the server's local time and never the browser's,
because a trip is planned in the destination's terms.

---

## Weather providers

Two providers behind one interface in `server/app/services/weather.py`, normalised so the UI
never branches on provider.

- **US coordinates → NOAA `api.weather.gov`.** Two-step, following the legacy reference client
  at `E:\GitRepos\palantir-for-family-trips\src\weather.js`: `GET /points/{lat},{lng}` returns a
  `properties.forecast` URL, which is then fetched for the daily periods. NOAA requires a
  descriptive `User-Agent`; requests without one are rejected. No API key.
- **Everywhere else → Open-Meteo.** Single call with a date range, daily max/min and a weather
  code. No API key.

Provider selection is by coordinate bounding box for the US (including Alaska and Hawaii), with
a fallback to Open-Meteo whenever NOAA returns anything other than a usable forecast — NOAA is
authoritative inside its coverage and useless outside it, and the boundary is not worth being
clever about.

Normalised payload stored in `weather_cache.payload_json`:
```
{ date, condition_text, icon_key, temp_high_c, temp_low_c,
  precip_probability, provider, location_label }
```
`icon_key` comes from a shared mapping of condition text (and Open-Meteo's numeric weather code)
onto a small icon set — the legacy `getWeatherIconKey` in `src/weather.js` is a good starting
point for the text-matching rules. Temperatures are stored in Celsius and converted for display
per the user's locale; storing one unit avoids a class of conversion bugs.

Called server-side only, from a service, never in a render path. Cached for ~1 hour.

---

## REST endpoints

All under `/api/v1`, session auth, Pydantic schemas both directions.

### `GET /api/v1/itinerary`
Query: `trip_id` (required), `from` / `to` (optional date bounds; defaults to the whole trip).
Response:
```
{ trip: { start_date, end_date, timezone },
  days: [ { date,
            items: [ { id, suggestion_id, title, start_time, end_time, sort,
                       lat, lng, type, status,
                       vote_summary, comment_count } ],
            legs: [ { from_item_id, to_item_id, polyline, duration_s, distance_m,
                      is_fallback } ],
            weather: { condition_text, icon_key, temp_high_c, temp_low_c,
                       precip_probability, location_label } | null } ] }
```
Permission: `require_member`. Available in every stage. Legs and weather are served from cache;
this endpoint makes no external call.

### `POST /api/v1/itinerary/items`
Request: `{ trip_id, suggestion_id?, day, start_time?, end_time?, title? }`
Validates: `day` within the trip range; if `suggestion_id` is given, the suggestion belongs to
this trip and its status is `approved`.
Side effects: sets the suggestion's status to `scheduled`; assigns `sort` at the end of the day;
queues the route recomputation task for the affected day.
Permission: `require_main_admin` + `require_stage("planning", "holiday")`.
Emits `itinerary.item_created` and `suggestion.status_changed`.

### `PATCH /api/v1/itinerary/items/{id}`
Request: any of `day`, `start_time`, `end_time`, `title`.
Changing `day` queues route recomputation for **both** the old and the new day.
Permission: `require_main_admin`. Stage: planning/holiday.
Emits `itinerary.item_updated`.

### `POST /api/v1/itinerary/items/{id}/move`
Explicit reordering. Request: `{ direction: "up" | "down" }` or `{ day, position }`.
Rewrites `sort` for the moved item only, using the sparse integer scheme; renumbers the whole
day only when the gap between neighbours is exhausted.
Permission: `require_main_admin`. Stage: planning/holiday.
Emits `itinerary.reordered` with the affected day's ordering.

NOTE: this endpoint exists instead of a drag-and-drop bulk-reorder payload because *list*
drag-and-drop stays deferred per `design-system.md`. The day-timeline mode's drag editing
(see "Day view — two switchable modes") changes item *times* through the ordinary
`PATCH /itinerary-items/{id}` — it needs no bulk-reorder endpoint either, so the API shape
holds for both modes.

### `DELETE /api/v1/itinerary/items/{id}`
Removes the item and returns its suggestion's status from `scheduled` to `approved` — back into
the pool, not gone. Queues route recomputation for the affected day.
Permission: `require_main_admin`. Stage: planning/holiday.
Emits `itinerary.item_deleted` and `suggestion.status_changed`.

### `GET /api/v1/itinerary/weather`
Query: `trip_id`, optional `date`.
Serves `weather_cache`; a stale entry (older than the TTL) triggers a background refresh and
returns the stale value immediately rather than blocking the response.
Permission: `require_member`. In End stage, cached values only, no refresh queued.

### `GET /api/v1/itinerary/export.ics`
Returns `text/calendar` with `Content-Disposition: attachment`.
One `VEVENT` per item: timed items use `DTSTART`/`DTEND` in the trip's timezone; untimed items
become all-day events (`VALUE=DATE`). `UID` is stable on the item id plus the instance host so
re-importing updates rather than duplicates. `SUMMARY` is the effective title; `LOCATION` is the
suggestion's address from `place_snapshot_json`; `DESCRIPTION` carries notes and a deep link back
into Kindred. `X-WR-CALNAME` is the trip name.
Permission: `require_member`. Available in every stage including End.

---

## WebSocket events

### Emitted
| Event | Payload | When |
|---|---|---|
| `itinerary.item_created` | full item | POST succeeds |
| `itinerary.item_updated` | full item, plus previous day when it changed | PATCH succeeds |
| `itinerary.reordered` | `day`, ordered item ids | move succeeds |
| `itinerary.item_deleted` | `id`, `day` | DELETE succeeds |
| `itinerary.routes_updated` | `day`, legs | route task completes |
| `itinerary.weather_updated` | `date`, weather payload | weather refresh completes |

### Consumed
| Event | Effect |
|---|---|
| `suggestion.updated` | refresh the item's denormalised title/location |
| `suggestion.moved` | queue route recomputation for days containing that suggestion |
| `suggestion.deleted` | remove dependent items and recompute routes |
| `stage.changed` | re-evaluate editing affordances; show or hide the "now" marker |

---

## Route computation

Background task in `server/app/services/routes.py`, using the Directions client in
`services/google.py` behind the same fake-able interface as Distance Matrix.

1. For the affected day, take the ordered items that have coordinates.
2. Build the consecutive pairs — items 1→2, 2→3, and so on. Items without coordinates are
   skipped, and the pair spans across them (1→3 if item 2 has no location).
3. Round each pair's coordinates to the storage precision and look up `route_cache`.
4. Fetch only the missing legs, one Directions call per leg, and upsert them.
5. Delete `route_cache` rows for the trip that no longer match any required leg across all days.
6. Emit `itinerary.routes_updated`.

Per `architecture.md`, Directions is called **once per itinerary change per leg** — never on
read, never on render. A day whose legs are all cached costs zero calls, which is why reordering
a day usually costs nothing: the same drives recur in a different order.

Failure: a leg that cannot be routed is stored as a fallback marker so it is not retried on
every change. The map draws a dashed straight line between those two items, and the day view
shows no duration for that leg rather than a guess.

---

## UI behaviour

### Layout
Per `design-system.md`: map centre (~62%), side panel (~38%), and the **bottom timeline panel**
— time belongs at the bottom, which is the whole reason that slot exists in the layout.
Collapsible, because the map is primary. On mobile the timeline becomes a horizontal day strip
above the bottom tab nav, and the day view is a full-height sheet.

### The timeline scrubber — generic over any trip length
Reference interaction only: the legacy `TimelineBoard` at
`E:\GitRepos\palantir-for-family-trips\src\components\boards\TimelineBoard.jsx`. What is taken
from it is the *interaction shape*: a horizontal track divided into day columns, hour ticks
within days, a hover cursor that previews a position, a committed cursor, a distinct "now"
marker with a label, and click-or-drag scrubbing across the whole track.

**Explicitly not carried over:**
- The hardcoded four-day `DAYS` constant and fixed slot arithmetic. Kindred's timeline derives
  entirely from `trips.start_date`…`end_date` and must render a 2-day weekend and a 21-day trip
  equally well.
- Playback controls (play/pause/restart/speed). There is nothing to animate in a trip planner;
  they were scenario-demo furniture.
- Family lanes in a "Transit" row, and the fixed `travel`/`activities`/`support` row taxonomy.
  Kindred has one itinerary, not per-family transit lanes (see out-of-scope).
- Every visual choice: the dark spy/ops palette, hardcoded hex colours, all-caps micro-type with
  extreme tracking, and labels like "mission scrub". `CLAUDE.md` names this styling as what
  Kindred must not look like, and `design-system.md` bans it outright.

Density adapts to trip length:
- **Up to ~4 days** — day columns with hour ticks and labels every few hours.
- **~5 to 14 days** — day columns with morning/afternoon/evening subdivisions; hour labels drop.
- **Over ~14 days** — day columns only, with week boundaries marked; the panel scrolls
  horizontally rather than compressing days into illegibility.

Thresholds are named settings, not literals. Items render as blocks positioned by time, or in a
day's unscheduled band when untimed. The "now" marker appears only in the Holiday stage, updates
on a timer, and is labelled with the current date and time in the trip's timezone.

Keyboard: left/right arrows move by day, shift+arrows by hour, Home/End jump to trip start/end.
The scrubber is a labelled slider to assistive technology, not a bare div.

### Day view — two switchable modes (added 2026-08-11)

The day panel header carries a segmented **`Agenda | Timeline`** switcher (design-system
segmented pattern). The choice is UI state, persisted per user client-side (localStorage);
no schema change. Mobile defaults to Agenda; desktop remembers the last choice. Both modes
render the same selection state — switching never loses the selected item.

**Agenda mode** (the original design, unchanged): timed items in sequence with their times;
untimed items in a clearly separated "sometime today" band. Between consecutive mapped
items, a leg row shows drive duration and distance from `route_cache` — or "route
unavailable" for a fallback leg. Reordering uses explicit controls (no list drag).

**Timeline mode** — a horizontal time-axis track, video-editor style (interaction
reference: the legacy TimelineBoard scrubber; visual reference:
`design-preview/screen-itinerary-timeline.html`):

- **Axis:** hour ticks across a visible window, default 08:00–22:00; items outside the
  window are reachable by horizontal scroll, and edge affordances indicate off-screen
  items. Component tokens: `--daytrack-h`, `--daytrack-bar-h`, `--daytrack-snap` (15min).
- **Bars:** each timed item is a rounded bar positioned/sized by start/end, filled with
  its category colour (`--cat-*`), title + time inside when width allows (truncate
  gracefully; minimum render width for near-instant items). Bar height ≥ `--hit-target`.
- **Fixed category lanes (structure adopted from the legacy TimelineBoard,
  2026-08-11):** the track is horizontal bands with a left label gutter — one lane per
  category present that day (e.g. Meals, Activities, Stay) plus a dedicated **Travel
  lane** — so items of different kinds can never collide. Floating labels (drag bubble,
  now-chip) live in a thin **headroom band above the lanes**, and the hour ruler is its
  own strip below — nothing ever overlays a bar. Lanes for categories with no items that
  day are omitted. *Within* one lane, overlapping items still pack into sub-lanes —
  deterministic interval packing (sort by start, then duration; first free lane wins),
  a pure, unit-tested function.
- **Gaps are the point:** empty track is visibly empty. Drive legs render as compact
  chips in the Travel lane, positioned in their actual time window; when
  `route duration > gap between bars`, the chip tints `--color-warning` with the
  shortfall stated ("! 22 min — gap 10") — an impossible transition flags itself
  without any validation dialog.
- **Untimed shelf:** "sometime today" items sit in a thin shelf below the track;
  dragging one onto the track gives it a time.
- **Now-cursor:** a vertical accent line drifts across the track — Holiday stage,
  today's date only (same rule as the day-columns now marker).
- **Editing (main admin only; stage guard planning/holiday):** drag a bar to move it
  (duration preserved), drag either edge to resize; both snap to `--daytrack-snap`
  (15 min). During drag: ghost bar at the original position and a live time bubble
  ("12:30 → 13:00"). Drop commits `PATCH /api/v1/itinerary-items/{id}` with the new
  times — optimistic UI, rollback on error, toast with **Undo** on success (restores
  prior times via the same PATCH). Other members see bars move live over the existing
  `itinerary.*` WS events. Members get the identical view read-only: no handles, no
  drag cursor.
- **Keyboard parity (required):** selected bar + arrow keys nudge by one snap step,
  Shift+arrows resize, Enter opens the item — drag is never the only path.

Edge cases:
| Case | Behaviour |
|---|---|
| Bar dragged past midnight | Clamped to the day; a toast explains "use *move to day* to reschedule across days" |
| Two admins drag the same bar concurrently | Last write wins; both converge via the WS broadcast (same precedent as poll cells) |
| Untimed item dragged onto an occupied slot | Allowed — lane packing absorbs the overlap |
| End dragged before start | Blocked at minimum duration (one snap step) |

Each item shows its title, type icon, family colour accent from the linked suggestion's author,
vote summary, and comment count, and links through to the suggestion's full record. Located
items also carry an **"Open in Google Maps" action** (prominent on mobile, secondary on
desktop) using the universal deep link
`https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>` (+ `&destination_place_id`
when stored) — opens the native Maps app for navigation; a plain URL, no API key or quota.

Admin controls per item: move up, move down, move to day, edit times, remove. Removal opens a
confirm dialog (admin-destructive per `design-system.md`) stating that the suggestion returns to
the approved pool.

### Map layer
- Items for the selected day render as **numbered** pins showing the sequence.
- Route polylines join consecutive mapped items, decoded from `route_cache`.
- Fallback legs draw as a dashed straight line so an unroutable gap is visibly different from a
  real road.
- Days other than the selected one are hidden by default, with a "show whole trip" toggle that
  renders all days at reduced emphasis.
- Selection syncs across map, day view, and timeline — one selection state, three renderers.

### Weather strip
One cell per day, aligned with the timeline's day columns: icon, condition text, and high/low.
Beyond forecast range the cell reads "No forecast yet" — never a fabricated value. The location
label states which point the forecast is for, since a day's items may span a wide area; the
strip uses the day's first mapped item as the representative location.

### Export
A download action in the itinerary panel header, available to all members in every stage.

### Styling and motion
Token-only, both themes verified. The timeline needs its own component tokens
(`--timeline-track-h`, `--timeline-day-w`, `--timeline-cursor-w`). Motion 150–250 ms for cursor
moves, panel collapse, and item transitions; under `prefers-reduced-motion` the cursor jumps
rather than glides and the "now" marker stops animating.

### Empty states
- No trip dates set: "Set the trip dates to build the itinerary", with the admin action inline
  and an explanatory line for non-admins.
- Dates set, no items: "Nothing scheduled yet — approve suggestions and add them to a day", with
  the admin action inline.
- A day with no items: "Nothing planned for this day", quiet, not alarming — a free day is a
  legitimate plan.

---

## Edge cases and error states

| Case | Handling |
|---|---|
| Trip dates not set | Timeline shows the empty state; scheduling is blocked with a message pointing at the trip settings. `GET` still returns an empty structure rather than erroring. |
| Trip dates changed to exclude scheduled days | Existing items are **kept**, not deleted, and surfaced to the admin as "3 items now fall outside the trip dates" with a link to move them. Silently destroying confirmed plans would be indefensible. |
| Item scheduled on a day outside the range | `422` naming the valid range. |
| Scheduling a non-approved suggestion | `422` stating the current status; the client should not have offered it. |
| Suggestion deleted while scheduled | `map-suggestions` blocks deletion of a scheduled suggestion with `409`, so this cannot normally occur. If it does (direct database edit), the item renders with its title override and no location. |
| Item with no location | Renders on the day view and timeline; no pin, no route leg; the surrounding legs span across it. |
| All items on a day lack locations | No routes, no map pins; the day view works normally. |
| Two items at the same time | Both render; they overlap visually side by side. No conflict detection in v1 — the admin is trusted. |
| Overnight item (23:00–01:00) | `end_time` earlier than `start_time` is interpreted as crossing midnight and clamped to the day's end for rendering; the day view notes it continues into the next day. |
| Multi-day item | Not supported as one record; entered as one item per day (see out-of-scope). |
| Directions failure for a leg | Stored as a fallback marker, not retried on every change; dashed straight line on the map and no duration in the day view. |
| Directions quota exhausted | All new legs become fallbacks; the admin sees a banner. The itinerary remains fully usable. |
| Weather beyond forecast range | Cell reads "No forecast yet". Never fabricated. |
| Weather provider unavailable | Stale cached payload is served if present; otherwise the cell is empty with a quiet "Weather unavailable". Never blocks the itinerary. |
| NOAA returns no forecast for US coordinates | Falls back to Open-Meteo rather than showing nothing. |
| Timezone: trip in a different zone from the viewer | All day boundaries, times, and the "now" marker use `trips.timezone`. Displayed times are labelled with the trip's zone where ambiguity is possible. |
| DST transition inside the trip | Day boundaries follow the trip timezone's local dates, so a 23- or 25-hour day renders as one day. |
| Reorder races between two admin sessions | Server applies against current `sort` values and broadcasts the resulting order; both clients re-render from `itinerary.reordered`. Last write wins. |
| `sort` gaps exhausted | The day is renumbered in one transaction and the full new order broadcast. |
| End stage reached mid-edit | Guard rejects with `403`; the panel switches to read-only chrome. Export still works. |
| Export with no items | Returns a valid empty calendar rather than an error — an empty `.ics` is legitimate. |
| Very long trip (months) | Timeline scrolls horizontally at day granularity; the day view and map are unaffected. Route recomputation is scoped per day, so length does not multiply Directions cost. |
