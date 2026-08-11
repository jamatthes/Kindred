# itinerary-timeline — Tasks

Ordered implementation checklist. Each phase ends with a `Verify:` line that must pass before
moving on. Read `requirements.md` and `design.md` in this directory first.

Prerequisites: `foundation`, `families`, `map-suggestions` (suggestions reach `approved`), and
`voting-comments` (status transitions) are complete. `trips.start_date`, `end_date`, and
`timezone` are settable via `admin-console`.

---

## Phase 1 — Migrations

- [ ] Confirm `itinerary_items` matches `plan/architecture.md`; create it if absent: `id`,
      `trip_id` (FK, indexed), `suggestion_id` (FK, nullable), `day` (date), `start_time`
      (nullable), `end_time` (nullable), `title` (nullable override), `confirmed_by` (FK),
      `sort` (int), `created_at`, `updated_at`.
- [ ] Add a composite index on `(trip_id, day, sort)` — the day view's read path.
- [ ] Confirm `route_cache` matches `architecture.md`; create if absent. Add a unique index on
      the rounded coordinate tuple `(trip_id, from_lat, from_lng, to_lat, to_lng)` so the
      coordinate-keyed lookup is enforced, not merely intended.
- [ ] Confirm `weather_cache` matches `architecture.md`; create if absent. Add a unique index on
      `(lat, lng, date)` where lat/lng are the rounded grid key.
- [ ] Add a `route_cache` nullable `is_fallback` boolean (default false) so an unroutable leg is
      recorded rather than retried on every itinerary change. NOTE: this is a small addition to
      the schema in `architecture.md`; update that document when it lands.
- [ ] Run `alembic upgrade head` then `alembic downgrade -1` to confirm the migration reverses.

`Verify:` `alembic upgrade head` succeeds on an empty database; `\d itinerary_items`, `\d
route_cache`, and `\d weather_cache` show the columns and unique indexes above.

---

## Phase 2 — Models

- [ ] Add `server/app/models/itinerary.py` with `ItineraryItem`, relationships to `Trip`,
      `Suggestion`, and `User` (`confirmed_by`), and an `effective_title` helper falling back to
      the linked suggestion's title.
- [ ] Add `server/app/models/route.py` (`RouteCache`) and `server/app/models/weather.py`
      (`WeatherCache`).
- [ ] Add coordinate-rounding helpers in `server/app/models/geo.py`: `route_key(lat, lng)` at
      5 decimal places and `weather_key(lat, lng)` at 2. Every read and write of these caches
      goes through them — a raw float must never reach a cache lookup.
- [ ] Add the sparse-sort constants (step 100) to `core/config.py`, plus the timeline density
      thresholds (4 and 14 days) so they are named, not literals.
- [ ] Add trip-timezone-aware day arithmetic helpers. Never use server local time or browser
      time for day boundaries.

`Verify:` `pytest server/tests/test_models_itinerary.py` passes, including a rounding test
proving two coordinates differing below the precision produce the same cache key, and a
timezone test proving a day boundary follows `trips.timezone` rather than UTC.

---

## Phase 3 — Schemas

- [ ] Add `server/app/schemas/itinerary.py`: `ItineraryItemCreate`, `ItineraryItemUpdate`,
      `ItineraryItemMove` (direction, or day + position), `ItineraryItemOut`, `LegOut`,
      `DayOut`, `ItineraryOut`, `WeatherOut`.
- [ ] Validate `day` within the trip range in `ItineraryItemCreate` and `ItineraryItemUpdate`,
      returning a message naming the valid range.
- [ ] Validate that a supplied `suggestion_id` belongs to the trip and has status `approved`.
- [ ] `WeatherOut` carries the normalised shape only — `condition_text`, `icon_key`,
      `temp_high_c`, `temp_low_c`, `precip_probability`, `provider`, `location_label`. Add a
      docstring stating the UI must never branch on `provider`.

`Verify:` `pytest server/tests/test_schemas_itinerary.py` passes, including rejection of an
out-of-range day and of a non-approved `suggestion_id`.

---

## Phase 4 — Weather service

- [ ] Add `server/app/services/weather.py` with one interface and two implementations behind it.
- [ ] NOAA client for US coordinates: `GET /points/{lat},{lng}` → follow
      `properties.forecast` → daily periods. Send a descriptive `User-Agent`; NOAA rejects
      requests without one. Reference the legacy client at
      `E:\GitRepos\palantir-for-family-trips\src\weather.js` for the two-step shape.
- [ ] Open-Meteo client for everywhere else: one call with a date range, daily max/min and
      weather code.
- [ ] Provider selection by US bounding box (including Alaska and Hawaii), falling back to
      Open-Meteo whenever NOAA returns anything unusable.
- [ ] Normalise both into the single payload shape; store temperatures in **Celsius** only and
      convert at display time.
- [ ] Port the condition-text → `icon_key` mapping (legacy `getWeatherIconKey` is a good
      starting point) and extend it to cover Open-Meteo's numeric weather codes.
- [ ] Cache into `weather_cache` on the rounded grid key with a ~1h TTL. A stale entry is served
      immediately while a background refresh runs — never block a response on weather.
- [ ] No external call in the End stage; cached values only.
- [ ] Wrap both clients so tests fake them and never hit the network.

`Verify:` `pytest server/tests/test_service_weather.py` passes with faked clients, covering:
US coordinates route to NOAA; non-US route to Open-Meteo; NOAA failure falls back to
Open-Meteo; both providers normalise to an identical payload shape; a stale entry is returned
immediately and triggers exactly one refresh.

---

## Phase 5 — Route service

- [ ] Add `server/app/services/routes.py` using the Directions client in `services/google.py`
      behind the same fake-able interface as Distance Matrix.
- [ ] `required_legs_for_day(day)` builds consecutive pairs from ordered items that have
      coordinates, spanning across items that lack them (1→3 when item 2 has no location).
- [ ] `recompute_routes(trip_id, days)`: look up each leg by rounded coordinate key, fetch only
      the misses, upsert, then delete `route_cache` rows for the trip that match no required leg
      across all days.
- [ ] A leg that cannot be routed is stored with `is_fallback = true` and is **not** retried on
      subsequent itinerary changes.
- [ ] Never call Directions on a read path — only from this background task, triggered by
      itinerary mutations and by `suggestion.moved`.
- [ ] Refuse to run in the End stage.
- [ ] Never raise into the request that queued it; a routing failure must not fail an itinerary
      edit.

`Verify:` `pytest server/tests/test_service_routes.py` passes with the fake client, covering:
a fully cached day costs zero calls; reordering a day whose drives already exist costs zero
calls; an unroutable leg is stored as a fallback and not re-requested; stale legs are deleted
after an item is removed.

---

## Phase 6 — Router

- [ ] Add `server/app/routers/itinerary.py`.
- [ ] `GET /api/v1/itinerary` (`require_member`, all stages) returning days with items, legs,
      and weather — all from cache, **zero external calls**.
- [ ] `POST /api/v1/itinerary/items` (`require_main_admin` +
      `require_stage("planning","holiday")`): validates day range and approved status, sets the
      suggestion to `scheduled`, assigns `sort` at the end of the day, queues route recomputation.
- [ ] `PATCH /api/v1/itinerary/items/{id}`: a day change queues recomputation for **both** the
      old and new day.
- [ ] `POST /api/v1/itinerary/items/{id}/move`: explicit reorder using the sparse-integer
      scheme; renumber the day only when a gap is exhausted.
- [ ] `DELETE /api/v1/itinerary/items/{id}`: returns the suggestion to `approved` and queues
      recomputation.
- [ ] `GET /api/v1/itinerary/weather` serving cache with a background refresh on staleness.
- [ ] Broadcast `itinerary.item_created`, `.item_updated`, `.reordered`, `.item_deleted`,
      `.routes_updated`, `.weather_updated`, plus `suggestion.status_changed` on schedule and
      unschedule.
- [ ] Subscribe to `suggestion.moved` and `suggestion.deleted` to queue recomputation.
- [ ] Register the router in `main.py`.

`Verify:` In `/docs`: schedule an approved suggestion and confirm its status becomes
`scheduled`; move it up and down and confirm the order changes; delete it and confirm the
suggestion returns to `approved`; attempt to schedule a `proposed` suggestion and confirm `422`.

---

## Phase 7 — iCal export

- [ ] Add `server/app/services/ical.py` producing `text/calendar`.
- [ ] One `VEVENT` per item: timed items get `DTSTART`/`DTEND` in `trips.timezone`; untimed
      items become all-day events using `VALUE=DATE`.
- [ ] `UID` stable on item id plus instance host so re-import updates rather than duplicates.
- [ ] `SUMMARY` = effective title; `LOCATION` = the suggestion's address from
      `place_snapshot_json`; `DESCRIPTION` = notes plus a deep link back into Kindred;
      `X-WR-CALNAME` = trip name.
- [ ] Include a `VTIMEZONE` component for the trip's zone.
- [ ] `GET /api/v1/itinerary/export.ics` (`require_member`, **all stages including End**) with
      `Content-Disposition: attachment`.
- [ ] An itinerary with no items returns a valid empty calendar, not an error.

`Verify:` Download the `.ics` from `/docs`, import it into a real calendar application, and
confirm timed and all-day events land on the correct days in the trip's timezone.

---

## Phase 8 — Server tests

- [ ] Happy paths: schedule, edit, move up/down, move to another day, delete.
- [ ] Status side effects: scheduling sets `scheduled`; deleting returns `approved`.
- [ ] Permission tests: family admin and member get `403` on every mutation; all roles can
      `GET` and export.
- [ ] Stage-guard tests: every mutation rejected in `end`; `GET`, weather, and export still work.
- [ ] Date-range validation, including the "dates changed to exclude scheduled days" case —
      assert items are **kept**, not deleted.
- [ ] Sparse-sort tests: a normal reorder rewrites one row; an exhausted gap renumbers the day
      in one transaction.
- [ ] Timezone tests: day boundaries follow `trips.timezone`; a DST transition inside the trip
      still yields one day per date.
- [ ] Overnight item (`end_time` < `start_time`) is handled as crossing midnight.
- [ ] **Render-path test**: `GET /api/v1/itinerary` with faked Google and weather clients
      asserting **zero** external calls. Mark it in a comment as the enforcement of the hard rule.
- [ ] Export tests: timed vs all-day events; empty itinerary yields a valid calendar.

`Verify:` `pytest server/tests/test_router_itinerary.py` passes, with the zero-external-calls
test green.

---

## Phase 9 — Timeline scrubber component

Build generically. The legacy `TimelineBoard` at
`E:\GitRepos\palantir-for-family-trips\src\components\boards\TimelineBoard.jsx` is a reference
for **interaction shape only**.

- [ ] Add `web/src/features/itinerary-timeline/TimelineScrubber.jsx` deriving its entire extent
      from `trips.start_date`…`end_date` — no fixed day count, no hardcoded slot arithmetic.
- [ ] Interaction taken from the reference: day columns, hour ticks, a hover cursor previewing a
      position, a committed cursor, a distinct "now" marker with a label, click-or-drag scrubbing.
- [ ] **Do not carry over**: playback controls (play/pause/restart/speed), per-family transit
      lanes, the `travel`/`activities`/`support` row taxonomy, or any of its visual styling —
      dark spy/ops palette, hardcoded hex, all-caps micro-type with extreme tracking, or labels
      like "mission scrub". `CLAUDE.md` names that styling as what Kindred must not look like.
- [ ] Density adapts by trip length using the named thresholds: ≤4 days → hour ticks with labels;
      5–14 days → morning/afternoon/evening subdivisions; >14 days → day columns with week
      boundaries and horizontal scrolling rather than illegible compression.
- [ ] "Now" marker renders only in the Holiday stage, updates on a timer, and is labelled in the
      trip's timezone.
- [ ] Keyboard: left/right by day, shift+arrows by hour, Home/End to trip start/end. Expose as a
      labelled slider to assistive technology, not a bare div.
- [ ] Component tokens `--timeline-track-h`, `--timeline-day-w`, `--timeline-cursor-w`.
      Token-only styling; both themes verified.
- [ ] Motion 150–250 ms on cursor moves and panel collapse; under `prefers-reduced-motion` the
      cursor jumps and the "now" marker stops animating.
- [ ] Collapsible panel; on mobile it becomes a horizontal day strip above the bottom tab nav.

`Verify:` In the browser, render the timeline for a 2-day, a 9-day, and a 21-day trip and
confirm each is legible with the correct density; scrub with the mouse and with the keyboard;
confirm no raw hex appears anywhere in the component.

---

## Phase 10 — Day view and admin controls

- [ ] Day view in the side panel: timed items in sequence, untimed items in a clearly separated
      "sometime today" band.
- [ ] Leg rows between consecutive mapped items showing drive duration and distance from
      `route_cache`, or "route unavailable" for a fallback leg.
- [ ] Each item shows title, type icon, family colour accent from the linked suggestion's author,
      vote summary, and comment count, linking to the suggestion's full record.
- [ ] Admin controls per item: move up, move down, move to day, edit times, remove. Rendered only
      for the main admin — absent, not disabled, for everyone else.
- [ ] Remove opens a confirm dialog stating the suggestion returns to the approved pool.
- [ ] A "schedule a suggestion" action listing only `approved` suggestions.
- [ ] **No list drag-and-drop.** Explicit controls only in agenda mode, per
      `design-system.md`. Leave a code comment recording that this is a deliberate
      deferral, not an omission. (Time-editing by drag belongs to Phase 10b's timeline
      mode, not this list.)
- [ ] Empty states: no trip dates (admin action inline, explanatory line for others); dates but
      no items; a day with nothing planned (quiet — a free day is a legitimate plan).

`Verify:` In the browser as the main admin, schedule two suggestions onto a day, reorder them
with the move controls, and confirm a second signed-in member sees the new order without a
refresh and sees no admin controls.

---

## Phase 10b — Day timeline mode (added 2026-08-11)

Visual reference: `design-preview/screen-itinerary-timeline.html`. Spec: "Day view — two
switchable modes" in `design.md`.

- [ ] `Agenda | Timeline` segmented switcher in the day panel header; choice persisted
      client-side per user (localStorage); mobile defaults to Agenda.
  **Verify:** switch modes, reload — the choice sticks; selection survives the switch.
- [ ] Lane-packing utility as a pure function (sort by start then duration, first free
      lane), plus snap helper (15-min steps from `--daytrack-snap`).
  **Verify:** Vitest covers overlap stacking, identical starts, instant items, and snap
  rounding at both edges.
- [ ] Track render: hour ticks (08:00–22:00 window, horizontal scroll beyond), category-
      coloured bars with title+time when width allows, minimum bar width, untimed shelf
      below, component tokens `--daytrack-h`, `--daytrack-bar-h`, `--daytrack-snap`.
  **Verify:** a seeded day with two overlapping items renders in two lanes; token-only
  styling in both themes.
- [ ] Drive-leg connectors between consecutive located bars from `route_cache`; warning
      tint when route duration exceeds the gap.
  **Verify:** shrink a gap below the drive time in seed data — connector turns warning.
- [ ] Now-cursor drifting on today's track, Holiday stage only; respects
      `prefers-reduced-motion` (jumps instead of gliding).
  **Verify:** stage=holiday + today shows the cursor; planning stage does not.
- [ ] Admin drag/resize: pointer drag moves (duration preserved) and edge-resizes with
      snapping; ghost bar + live time bubble during drag; drop commits
      `PATCH /itinerary-items/{id}` optimistically with rollback; Undo toast restores
      prior times; midnight clamp with explanatory toast; minimum duration of one snap
      step; untimed shelf items draggable onto the track.
  **Verify:** Playwright as main admin — drag a bar 30 min later, confirm the agenda
      mode and a second member's view both show the new time without refresh; Undo
      restores it.
- [ ] Keyboard parity: arrows nudge by snap step, Shift+arrows resize, Enter opens the
      item; announced to assistive tech.
  **Verify:** move a bar entirely by keyboard; times persist identically to drag.
- [ ] Read-only member mode: no handles, default cursor, no drag; identical layout.
  **Verify:** as a member, bars render without handles and pointer drag does nothing.

---

## Phase 11 — Map layer and weather strip

- [ ] Numbered pins for the selected day's items showing sequence order.
- [ ] Route polylines decoded from `route_cache` joining consecutive mapped items.
- [ ] Fallback legs drawn as a dashed straight line, visibly different from a real road.
- [ ] Other days hidden by default, with a "show whole trip" toggle rendering all days at
      reduced emphasis.
- [ ] Selection synced across map, day view, and timeline — one selection state, three renderers.
- [ ] Weather strip aligned with the timeline's day columns: icon, condition text, high/low,
      converted from stored Celsius per the user's locale.
- [ ] Beyond forecast range the cell reads "No forecast yet" — never a fabricated value.
- [ ] Location label states which point the forecast is for, using the day's first mapped item.
- [ ] Subscribe to `itinerary.routes_updated` and `itinerary.weather_updated` for live refresh.

`Verify:` In the browser, select a day and confirm numbered pins and route lines appear; remove
an item and confirm the routes redraw; confirm a day beyond forecast range shows "No forecast
yet" rather than a value.

---

## Phase 12 — Web tests, docs, and handoff

- [ ] Vitest: timeline renders correctly at 2, 9, and 21 days with the right density; the "now"
      marker appears only in the Holiday stage; keyboard scrubbing moves the cursor.
- [ ] Day view separates timed and untimed items; leg rows show durations; fallback legs show
      "route unavailable".
- [ ] Permission-gated UI: admin controls absent for members; export available to all.
- [ ] A test asserting no drag-and-drop handlers are bound on itinerary items.
- [ ] Playwright smoke extension, completing the path named in `architecture.md`: login →
      create suggestion → vote → confirm → **itinerary shows it**.
- [ ] Update `plan/architecture.md` to record `route_cache.is_fallback`.
- [ ] Re-read `requirements.md` and `design.md` against what shipped; update in the same commit
      if behaviour diverged.
- [ ] Note the handoff to `holiday-stage`: the "now / next up" mobile view consumes this
      feature's day data and is built there, not here.

`Verify:` `npm test` in `web/` passes; the Playwright smoke run completes login → create → vote
→ confirm → itinerary against the compose stack; `plan/architecture.md` lists
`route_cache.is_fallback`.
