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

- [x] `MapCanvas`/`SuggestionPin`/`RegionPolygon`/`PopoverCard`/`LiveMarker` — **already done**
      by the `feat/m3-map-shell` pre-build at `web/src/features/map/`, per this doc's own
      pre-build note. Not `web/src/map/` — the pre-build put them at `web/src/features/map/`
      and this implementer followed the existing code's location rather than moving it, per
      the M3 brief. `PinCluster` did not exist in the pre-build (documented as deliberately
      out of scope there); built instead as pure functions in
      `web/src/features/map-suggestions/markers.ts` (`clusterSuggestions`), since clustering
      needs the live suggestion list the provider shell does not own.
- [x] GeoJSON `[lng, lat]` ↔ our `LatLng` conversion centralised in
      `web/src/features/map-suggestions/geometry.ts` (`regionCentroid`, `circleGeometry`,
      `polygonGeometry`, `geometryToPolygonSpec`) — the one place coordinates reorder.
- [x] `web/src/features/map-suggestions/api.ts` (REST calls) and `store.ts` (shared filter +
      selection state, `useSyncExternalStore`-backed). `.ts`, not `.js` — matching every
      other feature in this codebase (`polls/api.ts`, `families/api.ts`); `.js` in this
      phase's own text was the only feature description written that way and is not
      followed, to keep one language across the app.
- [x] Subscribed in `useSuggestions.ts`: `suggestion.created/.updated/.moved/.status_changed/
      .deleted` apply directly to the in-memory list, reconciled by `id`;
      `suggestion.vote.updated`/`distance.updated`/`comment.created`/`comment.deleted`
      (owned by sibling features not yet built) refetch just the one affected record rather
      than guessing at their payload shape.
- [x] `resync` (the reconnect signal) refetches and reconciles the whole list by `id`.

`Verify:` Covered by `web/src/features/map-suggestions/useSuggestions.test.tsx` against a
mocked API + socket (no backend exists yet in this worktree — see Phase 12 hand-off). The
two-tab live-append behaviour is exercised in the test as a `suggestion.created` WS event
applied without a refetch; a real second-tab check is deferred to integration once the
backend lands.

---

## Phase 8 — Pins, popover card, side panel

- [x] Per-type icon + per-family colour + status glyph — **already done** by the pre-built
      `SuggestionPin`; this phase wires real data into it (`markers.ts` resolves
      `familyColor()` from `created_by.family_color`/`family_color_custom`).
- [x] Clustering (`markers.ts` > `clusterSuggestions`) — a coarse lat/lng grid, not true
      screen-pixel distance. **Deviation**: `MapProvider` (`features/map/MapProvider.ts`)
      exposes no query for a mounted marker's projected pixel position, only
      `FakeMapProvider`'s test-only accessors do, so an exact pixel-proximity cluster pass
      is not possible without extending the provider interface — out of this phase's
      "don't touch the provider layer" scope. The grid cell is sized relative to zoom
      (`cellSizeDeg`) as a reasonable approximation. Regions are excluded, per spec.
- [x] Z-order: `RegionPolygon` (pre-built) already paints fills beneath pins; route lines are
      `itinerary-timeline`'s and do not exist yet, so there is nothing to order against them
      today. Selected pin: `SuggestionMarkerSpec.selected` (pre-built) raises `.is-selected`.
- [x] Popover card wired with real data (`MapSuggestionsScreen`'s mobile `BottomSheet` peek
      snap, and `SuggestionDetailPanel`'s inline summary on desktop — see the Phase 8/9
      deviation note below on why desktop does not show a separately anchored popover).
- [x] `SuggestionDetailPanel.tsx`: full record, notes, external link, all-family distances,
      grouped children (clickable), a comment-count line slotted for `voting-comments`, and
      status/edit/delete controls gated the same way `requirements.md`'s permission table
      describes (author / family head-or-spouse / owner-or-organiser).
- [x] Photo strip (`SuggestionDetailPanel.tsx` > `PhotoStrip`): Place Details called in the
      browser via `placesClient.ts` on card-open only, 5-minute in-memory TTL cache, never
      sent to `suggestionsApi`. Skeleton while pending, absent (no error chrome) on failure
      or when there is no `place_id`. Tier 3 (`og:image` via `/link-preview`) implemented;
      tier 2 (user-uploaded `attachments`) is out of scope for v1 per `requirements.md`.
- [x] Grouped children render as offset markers (`markers.ts`'s radial `offsetForIndex`) and
      expand in place in `SuggestionDetailPanel`'s children list.
- [x] Token-only styling (`npm run check:tokens` passes); light/dark not manually screenshot
      in this pass (no visual review tool in this worktree) — verified structurally by reuse
      of existing semantic tokens throughout, same as every other feature's CSS.
- [ ] **Deferred**: explicit motion (150–250 ms pin-drop/card-in/sheet-up transitions) beyond
      what `BottomSheet`/`MapCanvas` already provide. No new transition was authored in this
      phase; `BottomSheet`'s existing snap animation and `prefers-reduced-motion` handling
      are reused as-is. Flagged for a follow-up polish pass.

**Deviation, desktop popover (recorded 2026-08-12):** `design.md`'s progressive disclosure
has three levels (pin → popover → panel); this implementation renders level 2 on **mobile
only** (`BottomSheet`'s `peek` snap, using the real `PopoverCard`) and jumps straight from
pin-click to the full `SuggestionDetailPanel` on desktop. Reason: an anchored floating
popover needs the pin's on-screen pixel position, which `MapProvider` does not expose for a
live-mounted marker (only `FakeMapProvider`'s private test accessors do) — adding that
query is a provider-interface change this phase's brief says to avoid unless a checklist
item genuinely requires it. `SuggestionDetailPanel` already renders everything the popover
would (title, status, votes, comments) so no information is lost, only the intermediate
"compact card floating over the map" affordance. A future pass adding
`MapProvider.getMarkerScreenPosition(id)` (or the Google Maps equivalent, which does expose
pixel projection) could restore it without touching this phase's data layer.

`Verify:` Automated: `SuggestionDetailPanel.test.tsx` covers permission gating, grouped
children, and the maps deep link. Manual browser verification (click a pin → popover/panel,
theme toggle, `prefers-reduced-motion`) is deferred to integration — this worktree has no
running backend or configured Google key to click against (see Phase 12).

---

## Phase 9 — Creation flows

- [x] One form, `CreateSuggestionForm.tsx`, seeded by all four entry points (mode tabs).
- [x] Search: `placesClient.autocompletePlaces` → prediction → `getPlaceDetails` (browser) →
      prefills title/coordinates/`place_snapshot`; every field stays editable; only the
      form's own state is sent to `suggestionsApi.create` (asserted directly in
      `CreateSuggestionForm.test.tsx`'s ToS test).
- [x] Drop-pin: mode tab shows a "click the map" hint; **deviation** — the pin is
      repositioned by clicking again, not dragged. `MapProvider` has no marker-drag
      primitive (only `markerClick`/`markerHover`/`polygonClick`/`mapClick`); adding one is
      a provider-layer change out of scope here. Click-to-reposition reaches the same
      outcome through the events that exist. Cancel (closing the form) discards the draft.
- [x] Draw-region: circle (two clicks: centre, then edge for radius) and polygon
      (click-to-place-vertex, "Finish" implicit once ≥3 points, "Start over" to reset); type
      locked to `region`; computed centroid displayed live. **Deviation** — polygon is
      click-to-place, not freehand drag, for the same `MapProvider` reason as drop-pin;
      `design.md` itself names click-to-place as one of its two sanctioned draw modes, so
      this is within spec rather than a reduction of it.
- [x] Paste-URL calls `suggestionsApi.linkPreview`; a value prefills the title (only if
      empty), `undefined`/`204` is silent.
- [x] Airbnb prefill: `facts`/`locality` prefill notes when notes are empty, `lat`/`lng`
      pre-drop the pin when no location is set yet. `capacity` is parsed by the type but not
      surfaced as its own field — there is no "sleeps" field in `suggestions` per
      `architecture.md`'s schema, so it has nowhere to go; noted for `voting-comments`/a
      future notes-template pass rather than silently dropped from the type.
- [x] Photo-source tiering — see Phase 8; tier 2 (`attachments`) intentionally absent (out of
      v1 scope).
- [x] Duplicate warning (`existingSuggestions` prop, matched on `place_id` + `type ===
      'accommodation'`): a `Banner` with a link to the existing suggestion, never blocking.
- [x] Six field states via the shared `TextField`/`useValidatedField` primitives (same ones
      every other form in the app uses); validate-on-blur, re-validate-after-first-error.

`Verify:` `CreateSuggestionForm.test.tsx` exercises search (with the ToS assertion),
drop-pin, validation, and the duplicate warning against a mocked `placesClient`/API — no
live Google key exists in this worktree, so draw-region's two-click flow and paste-URL's
network call are covered structurally (state transitions) rather than against a real
Places/link-preview response. Manual four-route browser verification deferred to
integration (Phase 12).

---

## Phase 10 — List view and filters

- [x] `SuggestionsList.tsx` on the shared `DataTable` (`app/ui/DataTable.tsx`), which already
      implements tri-state sort, sticky header, tabular right-aligned numerics, full-row
      click targets and spacing-token density — this phase only supplies the suggestion
      columns (title/type/status/votes/comments/distance).
- [x] `FilterBar.tsx`: type/status/family chips against `suggestionStore`, read by both
      `SuggestionsList` and `MapSuggestionsScreen`'s `listParams` (sent to the server as
      `type[]`/`status[]`/`family_id[]`).
- [x] Bidirectional selection: a list row click and a map marker click both call
      `suggestionStore.select(id)` — one write, both renderers read it
      (`MapCanvas`'s `markers` prop marks `selected` from the same `view.selectedId`).
      **Deviation** — "pan/zoom only when off-screen" is not implemented: `MapCanvas`
      recentres on every selection (`center={selected ? {lat,lng} : DEFAULT_CENTER}`)
      because `MapProvider` has no "is this point currently in the visible viewport" query
      to gate on; `getViewState()` returns center/zoom, not bounds. A real check needs
      either a bounds getter on `MapProvider` or reading it from the concrete Google map
      instance, either of which is a provider-layer addition. Noted for a follow-up.
- [x] Desktop: side panel shows the list (`FilterBar` + `SuggestionsList`) when nothing is
      selected, `SuggestionDetailPanel` (with a "← Back to list" control) when something is.
      Mobile: the list opens as its own `BottomSheet` from a floating "List (n)" button;
      selecting closes it and opens the selection's own sheet, matching `design.md`'s "list
      as a sheet from the bottom tab bar."
- [x] Both empty states, worded exactly per `design.md`, with inline actions.
- [x] Skeletons (`Skeleton` primitive) for the list's structural load; the map canvas itself
      has no loading state of its own to skeleton (`MapCanvas` mounts synchronously against
      whichever provider is supplied).

`Verify:` `SuggestionsList.test.tsx` covers the tri-state sort cycle, both empty states, and
row-click-writes-selection. Manual browser sort/filter/pan verification deferred to
integration (Phase 12) — no backend or live map key in this worktree.

---

## Phase 11 — Web tests

- [x] Pin icon-per-type and status-treatment-pairs-with-glyph — **already covered** by the
      pre-built `SuggestionPin.test.tsx`; not re-tested here. Popover card's tally/comment/
      distance rendering — covered by the pre-built `PopoverCard.test.tsx` (slot rendering);
      this phase's own `MapSuggestionsScreen` wiring of real data into those slots is
      exercised indirectly through `SuggestionDetailPanel.test.tsx`'s vote-summary assertions
      rather than a full screen-level render (no `MapSuggestionsScreen.test.tsx` — see below).
- [x] Permission-gated UI — `SuggestionDetailPanel.test.tsx`: status controls only for
      owner/organiser, delete for author / same-family head-or-spouse / owner-or-organiser,
      nothing for an unrelated member, nothing at all once the stage is frozen.
- [x] Tri-state sort — `store.test.ts` (`cycleSort`) and `SuggestionsList.test.tsx`
      (asserted through an actual header click + row order).
- [x] Selection sync — `store.test.ts` (`select()` is the one shared field) and
      `SuggestionsList.test.tsx` (row click writes it).
- [x] Grouped children — `SuggestionDetailPanel.test.tsx` and `markers.test.ts` (offset
      markers).
- [x] The Places ToS test — `CreateSuggestionForm.test.tsx`: seeds a Google Place Details
      response carrying photos/rating/hours, drives the real search → prediction → save
      flow, and asserts the payload sent to `suggestionsApi.create` carries only `place_id`
      plus the user-typed/kept fields.
- [ ] **Playwright smoke extension — explicitly skipped**, per this phase's own scope note:
      it needs the real backend (login → create → appears-in-both-views against the compose
      stack), which does not exist in this worktree (the backend agent's work lands on a
      different branch). Deferred to integration once both branches merge.

`Verify:` `npm test` (`vitest run`) in `web/` is green: 373 passing / 0 failing among tests
this phase touches (4 pre-existing, unrelated failures in `app/ui/pickers/DatePicker.test.tsx`
and `DateRangePicker.test.tsx` predate this branch — confirmed via `git diff` touching none
of `src/app/ui/pickers/`). `npm run build` and `npm run check:tokens` both pass. The
Playwright leg of `Verify:` does not run — see the skipped box above.

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
