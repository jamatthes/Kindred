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

- [ ] Add `web/src/features/distances/` with the API client and a `DistanceChip` component.
- [ ] Format duration first: "2h 40m from Parkers"; under an hour "35m from Parkers".
- [ ] Estimate state: distance only, muted, explicitly marked —
      "~48 km from Parkers · driving time pending" — with a tooltip explaining the fallback.
- [ ] `no_route`: "No driving route from Parkers", with a tooltip about ferries or flights.
      Information, not an error.
- [ ] `failed`: "Distance unavailable", quiet; the main admin additionally sees a retry
      affordance calling the recompute endpoint.
- [ ] `no_home`: "Home address not set", linking that family's admin to the address form.
- [ ] Region destinations append "to the centre of" in the tooltip.
- [ ] Every state pairs colour with text and an icon — colour never carries meaning alone.
- [ ] Do **not** use the preference ramp (`--scale-pref-0…10`) for distance. That ramp means
      group preference; reusing it here would make two different meanings look identical.
- [ ] Token-only styling; verify light and dark.

`Verify:` In the browser, a newly created suggestion shows a muted estimate chip that sharpens
into a real duration without a refresh; toggle the theme and confirm no raw colour leaks.

---

## Phase 9 — Placement and live updates

- [ ] Popover card: the caller's own family chip only, keeping the card glanceable.
- [ ] Side panel / bottom sheet: own family first, then an expander listing every family with
      its colour accent from the `--family-1…8` slots.
- [ ] List row: own family's value, right-aligned with tabular figures per the data-table pattern.
- [ ] Subscribe to `distance.updated` and swap the specific chip in place; subscribe to
      `suggestion.moved` to revert affected chips to the estimate state.
- [ ] Crossfade of 150–250 ms on the estimate → real transition; suppressed under
      `prefers-reduced-motion`. Never a spinner — an estimate is already a real number.
- [ ] Refetch distances for visible suggestions on WS reconnect.

`Verify:` With two browser tabs open, move a pin in one and watch the other's chips revert to
estimates and then resolve to new values, all without a refresh.

---

## Phase 10 — Sorting

- [ ] Add distance to the suggestion list's tri-state sort (asc → desc → original).
- [ ] Default to the caller's own family's values.
- [ ] Add a perspective selector to sort by another family's distances; the column header
      states whose perspective is active so a sorted list is never ambiguous.
- [ ] Switching perspective refetches via `GET /api/v1/distances?family_id=` rather than
      re-requesting the whole suggestion list.
- [ ] Ordering: real values ascending → estimates (marked) → `failed` / `no_home` →
      `no_route` last.
- [ ] Share filter and sort state with `map-suggestions`' store so map and list stay in step.

`Verify:` In the browser, sort by distance through all three states, switch the perspective to
another family, and confirm the header names that family and the order changes accordingly.

---

## Phase 11 — Degraded mode and admin affordances

- [ ] When rows are broadly `failed` (quota exhausted, key missing), show the main admin a
      banner explaining that the distance service is unavailable and estimates are being shown.
      Members see estimates without an alarming banner — the trip still works.
- [ ] Main admin force-recompute available from the suggestion side panel (single) and from
      the admin console (whole trip), each stating `estimated_api_calls` before running.
- [ ] Confirm the ops guardrails from `architecture.md` are in place: quota caps at free-tier
      thresholds, a billing alert, and the **server** key restricted by IP (separate from the
      browser key restricted by HTTP referrer).

`Verify:` Point the server key at an invalid value, restart, create a suggestion, and confirm
the app stays fully usable with estimates everywhere and an admin-only banner — no error page,
no blocked suggestion creation.

---

## Phase 12 — Web tests and docs

- [ ] Vitest: chip renders each of the five states with correct text and icon; estimate shows
      no duration; duration formatting for both over and under an hour.
- [ ] Sort ordering test covering the real → estimate → failed → no_route sequence.
- [ ] Permission-gated UI: recompute affordance renders only for the main admin.
- [ ] A test asserting the distance chip does not use the preference ramp tokens.
- [ ] Update `plan/architecture.md`'s `distance_cache` row to include `status` and `attempts`
      now that the PROPOSED ADDITIONS are real.
- [ ] Re-read `requirements.md` and `design.md` against what shipped and update in the same
      commit if behaviour diverged.

`Verify:` `npm test` in `web/` passes; `plan/architecture.md` lists `distance_cache.status` and
`distance_cache.attempts`; both docs in this directory match shipped behaviour.
