# map-suggestions — Tasks

Ordered implementation checklist. Work top to bottom; each phase ends with a `Verify:` line
that must pass before moving on. Read `requirements.md` and `design.md` in this directory
first — especially the **HARD INVARIANT** section on the Places ToS in `design.md`.

Prerequisites: `foundation` (auth, sessions, WS, Docker) and `families` (families with
colours and geocoded homes) are complete.

---

## Phase 1 — Migration

- [x] Confirm `suggestions` exists as specified in `plan/architecture.md`; if `foundation`
      did not create it, write the Alembic migration now: `id`, `trip_id` (FK, indexed),
      `type`, `title`, `notes`, `status`, `created_by` (FK), `lat`, `lng`,
      `geometry_geojson` (JSONB), `place_id`, `place_snapshot_json` (JSONB), `external_url`,
      `created_at`, `updated_at`.
- [x] Add enum-or-check constraints for `type` (`region`/`accommodation`/`activity`/`meal`)
      and `status` (`proposed`/`shortlisted`/`approved`/`scheduled`/`rejected`).
- [x] Add a composite index on `(trip_id, status)` and one on `(trip_id, type)` — both list
      filters hit these.
- [x] Add an index on `place_id` (nullable, non-unique) to support grouping lookups.
- [x] Add a check constraint: `geometry_geojson IS NOT NULL` when `type = 'region'`, and
      `IS NULL` otherwise.
- [x] Run `alembic upgrade head` against a scratch database, then `alembic downgrade -1` to
      confirm the migration reverses cleanly.

`Verify:` `alembic upgrade head` succeeds on an empty database and `\d suggestions` in psql
shows every column, constraint, and index listed above.

> **NOTE (M3 implementation).** The one-file migration rule (`CLAUDE.md`, set after this
> checklist was written) supersedes "write the Alembic migration now": `suggestions` and the
> `poll_options.suggestion_id` foreign key were added **in place** to
> `alembic/versions/0001_schema.py`, not as a second revision. The verify step was run as
> written — `upgrade head` then `downgrade -1` against a scratch database, both clean — and
> then extended with the check the one-file rule actually needs: `\d suggestions` and
> `\d poll_options` from a migrated database were diffed against the same tables built by
> `create_all` from the models, and are identical down to constraint names. That is the
> contract `plan/architecture.md` > Migration policy states, and it is what the pytest suite
> (which builds its schema with `create_all`) depends on being true.

---

## Phase 2 — Models

- [x] Add `server/app/models/suggestion.py` with the SQLAlchemy 2 `Suggestion` model mapping
      every column, typed with `Mapped[...]` annotations.
- [x] Relationships: `trip`, `author` (`created_by` → `User`), and back-references from
      `suggestion_votes` and `comments` (comments are polymorphic — join on
      `subject_type='suggestion'` and `subject_id`).
- [x] Add a `centroid()` helper that derives `(lat, lng)` from `geometry_geojson`: circle →
      the point itself; polygon → vertex average. Pure function, no I/O.
- [x] Add a `haversine_m(lat1, lng1, lat2, lng2)` SQL expression helper in
      `server/app/models/geo.py` — reused by grouping here and by `distances`.
- [x] Unit-test `centroid()` for both shapes, including a polygon crossing no meridian and
      one that does, and confirm GeoJSON `[lng, lat]` ordering is respected.

`Verify:` `pytest server/tests/test_models_suggestion.py` passes, covering `centroid()` for
circle and polygon and the `[lng, lat]` ordering assertion.

---

## Phase 3 — Schemas

- [x] Add `server/app/schemas/suggestion.py`: `SuggestionCreate`, `SuggestionUpdate`,
      `SuggestionStatusUpdate`, `SuggestionOut`, `SuggestionListParams`, `LinkPreviewIn`,
      `LinkPreviewOut`.
- [x] Add a `RegionGeometry` validator enforcing the encoding in `design.md`: required
      `properties.shape`; circle needs positive `radius_m` clamped to the maximum; polygon
      needs a closed ring of ≥ 4 positions and a vertex-count cap.
- [x] `SuggestionCreate` validates geometry-iff-region and requires `lat`/`lng`.
- [x] `SuggestionOut` nests `created_by` (with `family_id` and `family_color`),
      `place_snapshot`, `vote_summary`, `distances`, `comment_count`, and one level of
      `children`. Add a comment in the file stating that no Google-sourced detail fields
      belong in this schema, ever.
- [x] Unit-test the geometry validator's rejection paths (open ring, too few points,
      negative radius, oversized radius, missing `shape`).

`Verify:` `pytest server/tests/test_schemas_suggestion.py` passes, with every geometry
rejection path asserted.

---

## Phase 4 — Service layer

- [x] Add `server/app/services/suggestions.py` with the query-time grouping described in
      `design.md`: nest activities/meals under an accommodation on equal `place_id` or
      haversine proximity below the threshold, resolving ties by nearest then oldest.
- [x] Put the proximity threshold (150 m) and move epsilon (25 m) in `core/config.py` as
      named settings, not literals in the query.
- [x] Add `list_suggestions(...)` applying trip scope, filters, sort, and grouping, and
      joining vote tallies, comment counts, and `distance_cache` rows in one query. Avoid
      N+1 — assert the query count in a test.
- [x] Add `moved_beyond_epsilon(old, new)` used by the router to decide whether to re-queue
      the distance task.
- [x] Add `server/app/services/link_preview.py`: http/https scheme check, DNS resolution
      followed by a private/loopback/link-local address rejection (SSRF guard), timeout,
      redirect limit, response-size cap, OpenGraph-then-`<title>` parsing, in-memory LRU with
      a short TTL. **No database writes.**
- [x] Fake the outbound fetch behind an interface so tests never touch the network.

`Verify:` `pytest server/tests/test_service_suggestions.py server/tests/test_link_preview.py`
passes, including a grouping test with a mixed cluster, an N+1 query-count assertion, and an
SSRF test proving a URL resolving to a private address is refused.

---

## Phase 5 — Router

- [x] Add `server/app/routers/suggestions.py` mounted at `/api/v1/suggestions`.
- [x] Implement `GET /` (list, `require_member`) with all query parameters from `design.md`.
- [x] Implement `POST /` (`require_member` + `require_stage("planning","holiday")`);
      server recomputes the centroid for regions rather than trusting the client.
- [x] Implement `GET /{id}` (`require_member`) returning the record plus its comment thread.
- [x] Add a `require_can_edit_suggestion(id)` dependency in `deps.py`: author, family admin
      of the author's family, or main admin.
- [x] Implement `PATCH /{id}` and `DELETE /{id}` behind that dependency and the stage guard;
      `DELETE` returns `409` when the suggestion is `scheduled` or referenced by an
      `itinerary_items` row, naming the day in the message.
- [x] Implement `PATCH /{id}/status` (`require_main_admin`), validating the transition table
      in `design.md` and rejecting `scheduled` with `422`.
- [x] Implement `POST /api/v1/link-preview` returning `200` or `204`.
- [x] Airbnb-aware extraction in the link-preview service per `design.md`: parse facts/
      locality from `og:title`/`<title>` (stable OG contract), plus best-effort `lat`/`lng`/
      `capacity` from embedded page JSON — regex-level, wrapped so any parse failure
      degrades to the plain OG result. Unit-test against a saved HTML fixture; never fetch
      airbnb.co.uk in tests.
- [x] Wire WS broadcasts: `suggestion.created`, `.updated`, `.moved`, `.status_changed`,
      `.deleted` to the trip room.
- [x] Queue the background distance task on create and on a move beyond the epsilon.
- [x] Register the router in `main.py`.

`Verify:` Start the API, open `/docs`, and manually exercise: create an accommodation via
`POST /api/v1/suggestions`; create a region and confirm the response centroid matches the
drawn shape; `PATCH` its status to `shortlisted`; attempt `PATCH .../status` to `scheduled`
and confirm `422`; attempt a `DELETE` as a non-owning member and confirm `403`.

---

## Phase 6 — Server tests

- [x] Happy path per endpoint: create (each of the four types), list, get, patch, delete.
- [x] Permission-denied tests: member editing another family's suggestion; family admin
      editing outside their family; non-admin changing status.
- [x] Stage-guard tests: every mutation returns the guard's rejection in `end` stage while
      `GET` still succeeds.
- [x] Transition tests covering each allowed and each forbidden status move.
- [x] Grouping tests: activity sharing a `place_id` with an accommodation nests; one 100 m
      away nests; one 5 km away does not; a tie resolves to the nearer parent.
- [x] Delete-blocked test: a scheduled suggestion returns `409`.
- [x] Move-epsilon test: a 5 m move queues no distance task, a 500 m move queues one.
- [x] A test asserting no Google detail field is ever persisted — create a suggestion with an
      inflated payload and confirm only `place_id` and user-authored fields land in the row.

`Verify:` `pytest server/tests/test_router_suggestions.py` passes with every case above green.

---

## Phase 7 — Map wrapper and web data layer

- [ ] Add `web/src/map/` wrapper components: `MapCanvas` (loads the Maps JS SDK once),
      `SuggestionPins`, `RegionOverlays`, `PinCluster`.
- [ ] Centralise the GeoJSON `[lng, lat]` ↔ Google `LatLng` conversion in one module; nothing
      else in the codebase may reorder coordinates.
- [ ] Add `web/src/features/map-suggestions/api.js` for the REST calls and
      `store.js` holding the shared filter + selection state used by both map and list.
- [ ] Subscribe to the five `suggestion.*` events plus `suggestion.vote.updated`, `distance.updated`,
      and comment events; reconcile by `id`; make own-event echoes idempotent.
- [ ] Refetch and reconcile the list on WS reconnect.

`Verify:` With the dev stack running, load the map with seeded suggestions; pins and regions
render; creating a suggestion in a second browser tab makes it appear in the first without a
refresh.

---

## Phase 8 — Pins, popover card, side panel

- [ ] Per-type pin iconography and per-family colour accents drawn from `families.color` via
      the `--family-1…8` semantic slots. Status is conveyed by icon or glyph as well as
      treatment — never colour alone.
- [ ] Clustering with a count and a composition hint; regions excluded from clustering.
- [ ] Z-order: region fills → route lines → pins → selected pin.
- [ ] Popover card: title, type, vote tally, comment count, distance chips, "Details" action.
      Compact, no scrolling.
- [ ] Side panel (desktop, ~38% of the 62/38 split) and bottom sheet (mobile) with the full
      record, notes, external link, all-family distances, grouped children, and slots for the
      comment thread and admin controls owned by `voting-comments`.
- [ ] Photo strip: call Places Details **in the browser** on card-open, render photos from the
      live response, hold it in an in-memory cache with a short TTL, and never POST it to the
      server. Skeleton while pending; absent on failure with no error chrome.
- [ ] Grouped children render as offset pins with a faint connector and expand in place within
      the parent card.
- [ ] Token-only styling throughout; verify light and dark, paying attention to region fill
      opacity and cluster badges.
- [ ] Motion at 150–250 ms for pin drop, card in, and sheet up; all suppressed under
      `prefers-reduced-motion`.

`Verify:` In the browser, click a pin → popover card appears; click "Details" → side panel
opens with a photo strip; toggle the theme and confirm no raw colour leaks; enable
`prefers-reduced-motion` in devtools and confirm transitions are suppressed.

---

## Phase 9 — Creation flows

- [ ] One create form seeded by four entry points.
- [ ] Places Autocomplete search → prediction → browser Place Details → prefill title,
      address, coordinates; every field editable; only form contents are submitted.
- [ ] Drop-pin mode: cursor change, one click places a draggable provisional pin, cancel
      removes it.
- [ ] Draw-region mode: circle and polygon tools, adjustable pre-save, type locked to
      `region`, computed centroid displayed.
- [ ] Paste-URL: calls `POST /api/v1/link-preview`; `200` prefills the title, `204` is silent.
- [ ] Airbnb prefill: when the preview carries `facts`/`locality`/`capacity` they prefill
      the notes and sleeps fields; when it carries `lat`/`lng` the pin pre-drops (user can
      still drag it). Absence of any field changes nothing.
- [ ] Photo-source tiering on the details view per `design.md`: place_id photos →
      attachments → `og:image` hero (hot-linked) → placeholder; upload always offered.
- [ ] Duplicate warning when an accommodation with the same `place_id` already exists, linking
      to the existing record; warning only, never a block.
- [ ] All six field states styled; validate on blur, re-validate on change after first error;
      error text beneath the field.

`Verify:` In the browser, create one suggestion by each of the four routes and confirm each
appears on the map and in the list with correct type, family colour, and status.

---

## Phase 10 — List view and filters

- [ ] Table with tri-state sort (asc → desc → original) on votes, distance, and category;
      sticky header; tabular figures with right-aligned numerics; full-row click targets;
      density from spacing tokens.
- [ ] Filter chips for type, status, and family, shared with the map through the same store.
- [ ] Bidirectional selection sync; pan/zoom only when the target is off-screen, never while
      the user is actively panning.
- [ ] Desktop: list occupies the side panel when nothing is selected, with a "List" toggle
      when something is. Mobile: list as a bottom sheet from the tab bar.
- [ ] Empty states: no suggestions ("No suggestions yet — drop the first pin", action inline)
      and no matches ("No suggestions match these filters", clear-filters action).
- [ ] Skeletons for the structural load of map panel and list.

`Verify:` In the browser, sort by votes through all three states, filter to a single type, and
confirm the map updates in step; select a row and confirm the pin highlights, then the reverse.

---

## Phase 11 — Web tests

- [ ] Vitest + Testing Library: pin renders the right icon per type; status treatment pairs
      colour with an icon or glyph; popover card shows tally, comment count, and distance chips.
- [ ] Permission-gated UI: status controls render only for the main admin; edit/delete render
      only for the author, their family admin, or the main admin.
- [ ] Tri-state sort cycles asc → desc → original.
- [ ] Selection sync in both directions.
- [ ] Grouped children expand within the parent card.
- [ ] A test asserting the client never sends Google detail fields to the server on create.
- [ ] Playwright smoke extension: log in → create a suggestion via search → confirm it appears
      in both map and list.

`Verify:` `npm test` in `web/` passes, and the Playwright smoke run against the compose stack
completes the login → create → appears-in-both-views path.

---

## Phase 11b — Poll decision → region seed (handoff from `polls`)

The `polls` feature (M2) ships `POST /polls/{id}/decision/seed-region` returning
`501 not_available`, and created `poll_options.suggestion_id` as a bare uuid column with
**no FK constraint** (the `suggestions` table did not exist yet). This phase completes both
ends. See `plan/features/polls/design.md` (decision + seed_region) for the contract.

- [x] Migration: add FK `poll_options.suggestion_id → suggestions.id` with
      `ON DELETE SET NULL`.
- [x] Implement `seed_region`: for a decided, geographic poll option, create a `region`
      suggestion centred on the option's `lat`/`lng` (default radius, `properties.shape:
      "circle"`), status `proposed`, `created_by` = acting main admin; write the new id back
      to `poll_options.suggestion_id`. Idempotent — returns the existing `suggestion_id` when
      already set.
- [x] Replace the `501` response with the real implementation; permission `require_main_admin`,
      stages planning/holiday.
- [x] Emit `suggestion.created`; the polls UI's "seed region" action becomes a link to the
      created region (wiring already present per `polls/tasks.md`).
- [x] Tests: non-geographic option → `422`; undecided poll → `409`; idempotent second call;
      FK null-out when the region suggestion is deleted.

`Verify:` in the browser — decide a geographic poll option, seed the region, confirm the
region appears on the map and the poll's decision banner links to it; delete the region and
confirm the poll option's link clears.

## Phase 12 — Docs and handoff

- [ ] Re-read `requirements.md` and `design.md` against what was built; update them in the
      same commit if behaviour diverged (docs-first is a hard rule).
- [ ] Confirm the ops guardrails from `architecture.md` are in place before real use: quota
      caps at free-tier thresholds, a billing alert, the browser key restricted by HTTP
      referrer, and the server key restricted by IP — two separate keys.
- [ ] Note any follow-ups for `voting-comments` (admin controls slot), `distances` (chips),
      and `itinerary-timeline` (scheduled status, route lines) in those features' docs.

`Verify:` Both docs in this directory match the shipped behaviour, and the Cloud Console shows
quota caps, a billing alert, and two separately restricted keys.

## Hand-off notes (server, M3)

- **`vote_summary` is `voting-comments`' to fill.** `SuggestionOut.vote_summary` already ships
  in its documented shape (`mode`, `count`, `average`, `up`, `down`, `my_vote`, `my_thumb`),
  currently as a zero tally. Fill it in `services/suggestions.py` — the marked
  `NOTE (voting-comments)` in `serialise()` — and add the tally join to `_base_query()` or a
  second grouped query beside `_comment_counts()`. Do **not** add a per-row lookup:
  `tests/test_service_suggestions.py` asserts the list costs exactly two queries. The `votes_*`
  sort keys are accepted and currently order by creation; point them at the real column in
  `_apply_sort()`. `comment_count` is already real, and `GET /suggestions/{id}` already returns
  the thread in `CommentOut` shape — the write routes for a suggestion thread are yours.
- **`distances` owns two placed hooks.** `services/suggestions.py::queue_distance_recompute` is
  a no-op called on create and on a move past the epsilon, and
  `SuggestionOut.distances` is an empty list of the documented `DistanceOut` shape. The epsilon
  behaviour is already tested through the hook (5 m does not reach it, 500 m does), so filling
  the function in needs no router change. `models/geo.py::haversine_m` is the SQL expression for
  the straight-line estimate; `haversine_m_py` is the same formula for Python callers.
  `settings.suggestion_move_epsilon_m` is the shared threshold — do not restate 25 anywhere.
- **`itinerary-timeline` completes the delete guard.** `DELETE /suggestions/{id}` returns
  `409 suggestion_scheduled` on `status = 'scheduled'`; when `itinerary_items` exists, add the
  row lookup and name the day in the message, per this doc's edge-case table. `scheduled` is
  refused by `PATCH /{id}/status` (`422`) and has no outgoing transition, so the itinerary is
  the only thing that can set or clear it.
- **The web agent's contract.** `GET /api/v1/suggestions` takes `type`, `status`, `family_id`
  (all repeatable), `sort`, `group`, `include_rejected`; `group=false` is the map's call and
  returns every child as a top-level row. Five WS events are emitted:
  `suggestion.created` / `.updated` / `.moved` / `.status_changed` / `.deleted`. Region
  geometry is GeoJSON `[lng, lat]` throughout — convert once, in the map wrapper.
  `boundary_source == "osm"` is what the "boundary © OpenStreetMap contributors" line keys off,
  and `"fallback_ellipse"` is the approximate-outline case that offers "refine the outline".
  Every capability flag the UI needs (`can_edit`, `can_delete`, `can_change_status`) is on the
  response — never re-derive one client-side.
- **The Places ToS is enforced in four places and must stay that way**: no column
  (`models/suggestion.py`), no schema field with `extra="forbid"` (`schemas/suggestion.py`), no
  server route returning details, and four tests that fail if any of those changes
  (`tests/test_schemas_suggestion.py`, `tests/test_router_suggestions.py`). The browser fetches
  photos, hours and ratings itself on card-open and never POSTs them back.
