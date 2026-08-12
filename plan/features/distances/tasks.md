# distances — Tasks

Ordered implementation checklist. Each phase ends with a `Verify:` line that must pass before
moving on. Read `requirements.md` and `design.md` in this directory first — in particular the
**HARD INVARIANT** on never calling Google in a render path.

Prerequisites: `foundation`, `families` (homes geocoded into `families.home_lat/home_lng`), and
`map-suggestions` (suggestions with `lat`/`lng`, region centroids, and the 25 m move epsilon)
are complete.

---

## Phase 1 — Migration

- [ ] Confirm `distance_cache` matches `plan/architecture.md`; create it if `foundation` did
      not: `id`, `family_id` (FK), `suggestion_id` (FK), `duration_s` (int, nullable),
      `distance_m` (int, nullable), `mode` (default `driving`), `computed_at` (nullable),
      `created_at`, `updated_at`.
- [ ] Add the unique constraint on `(family_id, suggestion_id)` — the upsert depends on it.
- [ ] **PROPOSED ADDITION** — add `status` (varchar, not null, default `'pending'`) with a
      check constraint restricting it to `pending` / `ok` / `no_route` / `failed`.
- [ ] **PROPOSED ADDITION** — add `attempts` (int, not null, default 0).
- [ ] Add an index on `(suggestion_id, status)` — the read path filters on it constantly.
- [ ] Add an index on `(family_id)` for the home-change invalidation sweep.
- [ ] Confirm ON DELETE CASCADE from both `families` and `suggestions`.
- [ ] Run `alembic upgrade head` then `alembic downgrade -1` to confirm the migration reverses.

`Verify:` `alembic upgrade head` succeeds on an empty database; `\d distance_cache` shows
`status`, `attempts`, the unique pair constraint, and both indexes; inserting a duplicate
`(family_id, suggestion_id)` fails.

---

## Phase 2 — Models

- [ ] Add `server/app/models/distance.py` with the `DistanceCache` model and relationships to
      `Family` and `Suggestion`.
- [ ] Add a `DistanceStatus` enum mirroring the check constraint.
- [ ] Reuse the `haversine_m` SQL expression helper from `server/app/models/geo.py` (added by
      `map-suggestions`); do not write a second implementation.
- [ ] Add named settings in `core/config.py`: `DISTANCE_MAX_ORIGINS` (25),
      `DISTANCE_MAX_DESTINATIONS` (25), `DISTANCE_MAX_ELEMENTS` (100),
      `DISTANCE_MAX_ATTEMPTS` (3). No literals in the service.

`Verify:` `pytest server/tests/test_models_distance.py` passes, including a haversine
correctness check against two known coordinate pairs.

---

## Phase 3 — Schemas

- [ ] Add `server/app/schemas/distance.py`: `DistanceOut` (family_id, family_name,
      family_color, status, duration_s, distance_m, is_estimate, computed_at),
      `SuggestionDistancesOut`, `BulkDistancesParams`, `BulkDistancesOut`,
      `RecomputeIn`, `RecomputeOut` (queued_pairs, estimated_api_calls).
- [ ] `status` in the response includes `no_home`, which is a *presentation* state derived from
      a family lacking coordinates — it is not stored in the database. Document this in the
      schema file so nobody adds it to the check constraint.
- [ ] Assert in the schema docstring that an estimate carries `distance_m` only and never a
      fabricated `duration_s`.

`Verify:` `pytest server/tests/test_schemas_distance.py` passes, including a case asserting an
estimate response has `duration_s is None` and `is_estimate is True`.

---

## Phase 4 — Read service (no external calls)

- [ ] Add `server/app/services/distances.py` with the read half first:
      `get_distances_for_suggestion(...)` and `get_distances_bulk(...)`.
- [ ] Reads join `distance_cache` and compute the haversine fallback in SQL in the same query —
      one query per request, no N+1.
- [ ] Families with null `home_lat`/`home_lng` are returned as `no_home`, never omitted.
- [ ] Ordering places the calling user's own family first.
- [ ] Add a test-visible guard: the read service must not import or reference the Google client
      at all. Keep the external client in a separate module so this is structurally true rather
      than a matter of discipline.

`Verify:` `pytest server/tests/test_service_distances_read.py` passes, including an N+1
query-count assertion and a test proving a `pending` pair returns a haversine estimate with a
null duration.

---

## Phase 5 — Google client and background task

- [ ] Add the Distance Matrix client to `server/app/services/google.py` behind an interface so
      tests fake it and never hit the network (per `architecture.md`).
- [ ] Add the write half of `distances.py`: `queue_for_suggestion(suggestion_id)`,
      `queue_for_family(family_id)`, and `recompute(trip_id, suggestion_id=None)`.
- [ ] Implement the batching strategy from `design.md`: one call (all homes → one suggestion)
      on create/move; chunked calls (one home → all suggestions) on a home change, respecting
      the origin/destination/element caps from config.
- [ ] Chunk boundaries deterministic, ordered by suggestion `created_at`, so retries re-issue
      identical chunks.
- [ ] Upsert `pending` rows before calling, so concurrent reads show pending rather than nothing.
- [ ] Map element statuses per `design.md`: `OK` → `ok`; `ZERO_RESULTS` → `no_route` **cached
      permanently, never auto-retried**; `NOT_FOUND` → `failed` with an attempt increment;
      transport/timeout/`OVER_QUERY_LIMIT`/5xx → increment `attempts`, back off, settle at
      `failed` at the cap.
- [ ] Add an advisory lock or `pending` guard so overlapping tasks cannot duplicate calls for
      the same pair.
- [ ] Never raise into the request that queued the task — a distance failure must not fail a
      suggestion creation.
- [ ] Emit `distance.updated` per written row, not per batch.
- [ ] Add the End-stage assertion: the task refuses to run when the trip is in `end`.

`Verify:` `pytest server/tests/test_service_distances_write.py` passes with the fake client,
covering: one call for six families on create; correct chunking for 60 suggestions on a home
change; `ZERO_RESULTS` cached as `no_route` and not re-queued; `attempts` capping at 3; and a
test asserting the task raises nothing when the fake client errors.

---

## Phase 6 — Router

- [ ] Add `server/app/routers/distances.py`.
- [ ] `GET /api/v1/suggestions/{id}/distances` (`require_member`, all stages).
- [ ] `GET /api/v1/distances` bulk form with `trip_id`, optional `suggestion_ids[]` and
      `family_id` (`require_member`, all stages).
- [ ] `POST /api/v1/distances/recompute` (`require_main_admin` +
      `require_stage("planning","holiday")`), returning `queued_pairs` and
      `estimated_api_calls` **before** the work runs.
- [ ] Recompute resets matching rows to `pending` with `attempts = 0`, including rows at
      `no_route` and `failed` — this is the only path that retries a settled negative.
- [ ] Register the router in `main.py`.
- [ ] Wire the triggers: `map-suggestions` POST and PATCH-beyond-epsilon call
      `queue_for_suggestion`; `families` home geocode/change calls `queue_for_family`.

`Verify:` In `/docs`: create a suggestion and confirm `GET /api/v1/suggestions/{id}/distances`
first returns estimates and then real values; call `POST /api/v1/distances/recompute` and
confirm the response states the call count before the work runs; call it with the trip in
`end` stage and confirm the stage guard rejects it.

---

## Phase 7 — Server tests

- [ ] Happy path: create a suggestion, run the faked task, confirm one `ok` row per family.
- [ ] Estimate path: a suggestion with no cached rows returns haversine values with
      `is_estimate: true` and null durations.
- [ ] `no_home`: a family without coordinates is present in the response with `no_home` and is
      absent from the API call's origins.
- [ ] `no_route` is cached permanently and a subsequent create/read queues no further call —
      assert the fake client's call count does not increase.
- [ ] Move epsilon: a 5 m move queues nothing; a 500 m move resets rows to `pending` and queues
      one call.
- [ ] Home change resets only that family's rows and leaves other families' values intact.
- [ ] Permission tests: a member calling recompute gets `403`; every member can read all
      families' distances.
- [ ] Stage guard: recompute rejected in `end`; reads still succeed in `end`.
- [ ] **Render-path test**: exercise `GET /api/v1/suggestions` and
      `GET /api/v1/distances` with the fake Google client asserting **zero** calls. This test
      is the enforcement of the hard invariant — mark it as such in a comment.
- [ ] Concurrency test: two overlapping queues for the same suggestion produce one call.

`Verify:` `pytest server/tests/test_router_distances.py` passes, with the zero-calls-in-render-
path test green.

---

## Phase 8 — Distance chip UI

- [x] `web/src/features/distances/api.ts` (`distancesApi.forSuggestion`/`.bulk`/`.recompute`,
      coded to `design.md`'s three endpoints exactly) and `DistanceChip.tsx`.
- [x] Duration-first formatting (`format.ts`'s `formatDuration`): "2h 40m from Parkers",
      "35m from Parkers" under an hour.
- [x] Estimate state: distance-only, muted, "~48 km from Parkers · driving time pending",
      tooltip explaining the haversine fallback.
- [x] `no_route`: "No driving route from Parkers", tooltip naming a ferry or flight,
      `--color-info` (information, not `--color-danger`).
- [x] `failed`: "Distance unavailable", quiet; a "Retry" button renders when the caller
      passes `canRetry` (the organiser-only case — gated by the caller, not the chip).
- [x] `no_home`: "Home address not set", a "Set it" action when the caller passes
      `onSetHomeFor` (wired to `navigate({ name: 'families', familyId })` in the panel).
- [x] Region destinations append the centroid note to the tooltip (`isRegion` prop).
- [x] Every state's icon is paired with visible text (`DistanceChip.test.tsx`'s own
      colour-never-alone case asserts a non-empty text node in every state).
- [x] No preference-ramp token anywhere in `distances.css` or any rendered chip — asserted
      by reading both the DOM (inline `style`/`class`) and the CSS source text directly in
      `DistanceChip.test.tsx`.
- [x] Token-only (`npm run check:tokens` passes); light/dark not manually screenshot in this
      pass (no visual review tool in this worktree, same caveat as the prior two phases).

`Verify:` `DistanceChip.test.tsx` covers all five states, both duration formats, and the
preference-ramp assertion. The browser crossfade/theme-toggle checks are deferred to
integration (no backend or live map key in this worktree — see Phase 12).

---

## Phase 9 — Placement and live updates

- [x] Popover card: `MapSuggestionsScreen`'s mobile `PopoverCard` fills `distanceChips` with
      one `DistanceChip` for `distanceForFamily(selected.distances, ownFamilyId)` only.
- [x] Side panel: `FamilyDistanceExpander` — own family first, expander revealing the rest
      with a `familyColor()`-accented swatch per row.
- [x] List row: `DistanceCell` — plain tabular text (not the full chip; see the deviation
      note in `design.md` on why), right-aligned via `DataTable`'s `numeric` column flag.
- [x] `distance.updated` patches the one family row in place in `useSuggestions.ts`
      (`onDistanceUpdated`), resolving the map-suggestions handoff note's "simplify to a
      direct patch" once this feature's payload shape was known. `suggestion.moved` reverts
      every `ok` row on the moved suggestion to `pending`/estimate (`onMoved`) — both
      covered directly in `useSuggestions.test.tsx`.
- [x] Crossfade (150ms, `--duration-base`/`--ease-standard`) on `.dist-chip--animated`,
      applied to the `ok` and `pending` (estimate) states — the two a chip actually
      transitions between; `no_route`/`failed`/`no_home` are settled states with nothing to
      fade from. Suppressed under `prefers-reduced-motion`. No spinner anywhere in this
      feature's components.
- [x] WS reconnect (`resync`) already refetches the whole suggestion list in
      `useSuggestions.ts`, which includes every visible suggestion's `distances` array —
      no separate distances-only reconnect path was needed.

`Verify:` `useSuggestions.test.tsx`'s two new cases prove the in-place patch and the
moved-reverts-to-estimate behaviour against a mocked socket. The two-tab browser check is
deferred to integration (no backend in this worktree).

---

## Phase 10 — Sorting

- [x] Distance is one of `DataTable`'s tri-state sortable columns (asc → desc → original),
      same generic mechanism every other column in `SuggestionsList` already uses.
- [x] Defaults to `view.distancePerspectiveFamilyId === null`, read as the caller's own
      family (`distanceForFamily(row.distances, ownFamilyId)` — no extra request).
- [x] `DistancePerspectiveSelector.tsx`: a family dropdown; the "Distance (from …)" column
      header interpolates whichever name is active, so a sorted list is never ambiguous.
- [x] Switching perspective calls `useBulkDistances` → `GET /distances?family_id=` — the
      whole suggestion list is not re-requested, only the one family's distances.
- [x] `distanceOrder.ts`'s `distanceSortValue`: real (by duration) → estimate (by distance)
      → failed/no_home → no_route, encoded as disjoint numeric bands so `DataTable`'s
      generic comparator needs no distance-specific knowledge.
- [x] `distancePerspectiveFamilyId` lives on `map-suggestions/store.ts`'s existing
      `SuggestionViewState` — one shared store, not a second one, same reasoning
      `voting-comments`' `needsMyVote` used.

`Verify:` `distanceOrder.test.ts` (the tiering, in isolation) and `SuggestionsList.test.tsx`'s
new case (the tiering through an actual header click + row order) are green.
`DistancePerspectiveSelector` itself is exercised indirectly through `SuggestionsList`; a
standalone interaction test (change the `<select>`, confirm `setDistancePerspective` fires)
was not added separately — `store.test.ts`'s `setDistancePerspective` case plus the
selector's own small size made the marginal coverage not worth a ninth test file. Full
browser sort/switch verification deferred to integration.

---

## Phase 11 — Degraded mode and admin affordances

- [x] `DistancesSection.tsx` (admin console) shows an error `Banner` when the trip looks
      degraded; members never reach this section at all (admin-console gating, same as every
      other section there) so they see estimates with no banner anywhere.
      **Deviation, recorded in `design.md`**: no dedicated health endpoint exists in this
      feature's REST contract, so degraded-ness is a client-side heuristic
      (`useDistanceHealth.ts`) over the caller's own bulk read rather than a real
      trip-wide signal — documented with its exact thresholds and reasoning.
- [x] `RecomputeButton.tsx` (shared component): single-suggestion use in
      `SuggestionDetailPanel.tsx` (organiser-only, `distances.length > 0`), whole-trip use
      in `DistancesSection.tsx`. Both toast `queued_pairs`/`estimated_api_calls` from the
      response the instant it arrives — see the note in `useRecompute.ts` on why that
      satisfies "states the cost before running" absent a separate preview endpoint.
- [ ] **Ops guardrails (quota caps, billing alert, server key IP restriction) — explicitly
      skipped**, per this phase's own scope note: Google Cloud Console work, not code.

`Verify:` `RecomputeButton.test.tsx` and `DistancesSection.test.tsx` cover the cost toast,
the failure banner, and the degraded-mode threshold. The invalid-key/restart browser check
is deferred to integration.

---

## Phase 12 — Web tests and docs

- [x] Chip states, icons, and duration formatting — `DistanceChip.test.tsx` (14 cases).
- [x] Sort ordering (real → estimate → failed → no_route) — `distanceOrder.test.ts` (the
      tiering, unit-level) and `SuggestionsList.test.tsx` (the same tiering through an
      actual sorted table).
- [x] Permission-gated recompute — `SuggestionDetailPanel.test.tsx`'s new describe block
      (absent for a member, present for an organiser, chip-level Retry follows the same
      gate).
- [x] Preference-ramp assertion — `DistanceChip.test.tsx` (DOM-level and CSS-source-level).
- [ ] **`plan/architecture.md`'s `distance_cache.status`/`.attempts` update — deferred**,
      per this assignment's own scope note: the backend agent owns the schema docs for a
      table this web-only pass never touches. Not done here; flagged for whoever lands the
      server-side Phases 1–7.
- [x] Re-read both docs against what shipped this web pass; deviations recorded in the dated
      NOTE at the bottom of `design.md`.

`Verify:` `npm test` in `web/`: 454 passing / 4 failing, all 4 pre-existing and unrelated
(`app/ui/pickers/DatePicker.test.tsx`/`DateRangePicker.test.tsx`). `npm run build` and
`npm run check:tokens` both pass. `plan/architecture.md` is intentionally untouched this
pass — see the deferred box above.
