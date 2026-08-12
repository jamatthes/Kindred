# distances — Tasks

Ordered implementation checklist. Each phase ends with a `Verify:` line that must pass before
moving on. Read `requirements.md` and `design.md` in this directory first — in particular the
**HARD INVARIANT** on never calling Google in a render path.

Prerequisites: `foundation`, `families` (homes geocoded into `families.home_lat/home_lng`), and
`map-suggestions` (suggestions with `lat`/`lng`, region centroids, and the 25 m move epsilon)
are complete.

---

## Phase 1 — Migration

- [x] Confirm `distance_cache` matches `plan/architecture.md`; create it if `foundation` did
      not: `id`, `family_id` (FK), `suggestion_id` (FK), `duration_s` (int, nullable),
      `distance_m` (int, nullable), `mode` (default `driving`), `computed_at` (nullable),
      `created_at`, `updated_at`.
- [x] Add the unique constraint on `(family_id, suggestion_id)` — the upsert depends on it.
- [x] **PROPOSED ADDITION** — add `status` (varchar, not null, default `'pending'`) with a
      check constraint restricting it to `pending` / `ok` / `no_route` / `failed`.
- [x] **PROPOSED ADDITION** — add `attempts` (int, not null, default 0).
- [x] Add an index on `(suggestion_id, status)` — the read path filters on it constantly.
- [x] Add an index on `(family_id)` for the home-change invalidation sweep.
- [x] Confirm ON DELETE CASCADE from both `families` and `suggestions`.
- [x] Run `alembic upgrade head` then `alembic downgrade -1` to confirm the migration reverses.

`Verify:` `alembic upgrade head` succeeds on an empty database; `\d distance_cache` shows
`status`, `attempts`, the unique pair constraint, and both indexes; inserting a duplicate
`(family_id, suggestion_id)` fails.

---

## Phase 2 — Models

- [x] Add `server/app/models/distance.py` with the `DistanceCache` model and relationships to
      `Family` and `Suggestion`.
- [x] Add a `DistanceStatus` enum mirroring the check constraint.
- [x] Reuse the `haversine_m` SQL expression helper from `server/app/models/geo.py` (added by
      `map-suggestions`); do not write a second implementation.
- [x] Add named settings in `core/config.py`: `DISTANCE_MAX_ORIGINS` (25),
      `DISTANCE_MAX_DESTINATIONS` (25), `DISTANCE_MAX_ELEMENTS` (100),
      `DISTANCE_MAX_ATTEMPTS` (3). No literals in the service.

`Verify:` `pytest server/tests/test_models_distance.py` passes, including a haversine
correctness check against two known coordinate pairs.

---

## Phase 3 — Schemas

- [x] Add `server/app/schemas/distance.py`: `DistanceOut` (family_id, family_name,
      family_color, status, duration_s, distance_m, is_estimate, computed_at),
      `SuggestionDistancesOut`, `BulkDistancesParams`, `BulkDistancesOut`,
      `RecomputeIn`, `RecomputeOut` (queued_pairs, estimated_api_calls).
- [x] `status` in the response includes `no_home`, which is a *presentation* state derived from
      a family lacking coordinates — it is not stored in the database. Document this in the
      schema file so nobody adds it to the check constraint.
- [x] Assert in the schema docstring that an estimate carries `distance_m` only and never a
      fabricated `duration_s`.

`Verify:` `pytest server/tests/test_schemas_distance.py` passes, including a case asserting an
estimate response has `duration_s is None` and `is_estimate is True`.

---

## Phase 4 — Read service (no external calls)

- [x] Add `server/app/services/distances.py` with the read half first:
      `get_distances_for_suggestion(...)` and `get_distances_bulk(...)`.
- [x] Reads join `distance_cache` and compute the haversine fallback in SQL in the same query —
      one query per request, no N+1.
- [x] Families with null `home_lat`/`home_lng` are returned as `no_home`, never omitted.
- [x] Ordering places the calling user's own family first.
- [x] Add a test-visible guard: the read service must not import or reference the Google client
      at all. Keep the external client in a separate module so this is structurally true rather
      than a matter of discipline.

`Verify:` `pytest server/tests/test_service_distances_read.py` passes, including an N+1
query-count assertion and a test proving a `pending` pair returns a haversine estimate with a
null duration.

---

## Phase 5 — Google client and background task

- [x] Add the Distance Matrix client to `server/app/services/google.py` behind an interface so
      tests fake it and never hit the network (per `architecture.md`).
- [x] Add the write half of `distances.py`: `queue_for_suggestion(suggestion_id)`,
      `queue_for_family(family_id)`, and `recompute(trip_id, suggestion_id=None)`.
- [x] Implement the batching strategy from `design.md`: one call (all homes → one suggestion)
      on create/move; chunked calls (one home → all suggestions) on a home change, respecting
      the origin/destination/element caps from config.
- [x] Chunk boundaries deterministic, ordered by suggestion `created_at`, so retries re-issue
      identical chunks.
- [x] Upsert `pending` rows before calling, so concurrent reads show pending rather than nothing.
- [x] Map element statuses per `design.md`: `OK` → `ok`; `ZERO_RESULTS` → `no_route` **cached
      permanently, never auto-retried**; `NOT_FOUND` → `failed` with an attempt increment;
      transport/timeout/`OVER_QUERY_LIMIT`/5xx → increment `attempts`, back off, settle at
      `failed` at the cap.
- [x] Add an advisory lock or `pending` guard so overlapping tasks cannot duplicate calls for
      the same pair.
- [x] Never raise into the request that queued the task — a distance failure must not fail a
      suggestion creation.
- [x] Emit `distance.updated` per written row, not per batch.
- [x] Add the End-stage assertion: the task refuses to run when the trip is in `end`.

`Verify:` `pytest server/tests/test_service_distances_write.py` passes with the fake client,
covering: one call for six families on create; correct chunking for 60 suggestions on a home
change; `ZERO_RESULTS` cached as `no_route` and not re-queued; `attempts` capping at 3; and a
test asserting the task raises nothing when the fake client errors.

---

## Phase 6 — Router

- [x] Add `server/app/routers/distances.py`.
- [x] `GET /api/v1/suggestions/{id}/distances` (`require_member`, all stages).
- [x] `GET /api/v1/distances` bulk form with `trip_id`, optional `suggestion_ids[]` and
      `family_id` (`require_member`, all stages).
- [x] `POST /api/v1/distances/recompute` (`require_main_admin` +
      `require_stage("planning","holiday")`), returning `queued_pairs` and
      `estimated_api_calls` **before** the work runs.
- [x] Recompute resets matching rows to `pending` with `attempts = 0`, including rows at
      `no_route` and `failed` — this is the only path that retries a settled negative.
- [x] Register the router in `main.py`.
- [x] Wire the triggers: `map-suggestions` POST and PATCH-beyond-epsilon call
      `queue_for_suggestion`; `families` home geocode/change calls `queue_for_family`.

`Verify:` In `/docs`: create a suggestion and confirm `GET /api/v1/suggestions/{id}/distances`
first returns estimates and then real values; call `POST /api/v1/distances/recompute` and
confirm the response states the call count before the work runs; call it with the trip in
`end` stage and confirm the stage guard rejects it.

---

## Phase 7 — Server tests

- [x] Happy path: create a suggestion, run the faked task, confirm one `ok` row per family.
- [x] Estimate path: a suggestion with no cached rows returns haversine values with
      `is_estimate: true` and null durations.
- [x] `no_home`: a family without coordinates is present in the response with `no_home` and is
      absent from the API call's origins.
- [x] `no_route` is cached permanently and a subsequent create/read queues no further call —
      assert the fake client's call count does not increase.
- [x] Move epsilon: a 5 m move queues nothing; a 500 m move resets rows to `pending` and queues
      one call.
- [x] Home change resets only that family's rows and leaves other families' values intact.
- [x] Permission tests: a member calling recompute gets `403`; every member can read all
      families' distances.
- [x] Stage guard: recompute rejected in `end`; reads still succeed in `end`.
- [x] **Render-path test**: exercise `GET /api/v1/suggestions` and
      `GET /api/v1/distances` with the fake Google client asserting **zero** calls. This test
      is the enforcement of the hard invariant — mark it as such in a comment.
- [x] Concurrency test: two overlapping queues for the same suggestion produce one call.

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

## Hand-off notes (server, M3)

- **The web agent's contract.** `GET /api/v1/suggestions/{id}/distances` returns
  `{suggestion_id, distances[]}` with the caller's own family first;
  `GET /api/v1/distances?suggestion_ids=&family_id=` returns `{distances: {suggestion_id: [...]}}`
  (no `trip_id` — the active trip is server-side, as everywhere else in v1);
  `POST /api/v1/distances/recompute` takes `{suggestion_id?}` and returns
  `{queued_pairs, estimated_api_calls}` **before** the work runs. `GET /api/v1/suggestions`
  already embeds the caller's own family's chip per row, and `GET /api/v1/suggestions/{id}`
  embeds every family's — the bulk endpoint is for the refetch case (switching the sort
  perspective), not for the first render.
- **Five states, and `is_estimate` is the one to branch on first.** `ok` (real duration and
  distance), `pending`/`failed` (estimate: distance only, **`duration_s` is always null** —
  never render a duration for an estimate, and never compute one client-side), `no_route`
  (both null; information, not an error), `no_home` (both null; actionable for that family's
  head). The server will never send an estimate carrying a duration — a validator refuses to
  build one — so a chip that needs a duration can trust `is_estimate: false`.
- **`distance.updated` arrives per row**, carrying `{suggestion_id, family_id, status,
  duration_s, distance_m, is_estimate: false, computed_at}`. Swap that one chip in place;
  do not refetch the list. On `suggestion.moved`, revert that suggestion's chips to the estimate
  state — the server has already reset those rows to `pending`.
- **Never show a spinner on a chip.** An estimate is a real number and renders immediately; the
  transition to the real value is a crossfade. A spinner would imply the first number was not
  information.
- **Do not use the preference ramp (`--scale-pref-0…10`) for distance.** That ramp means "how
  much the group likes this"; reusing it for "how far away this is" would make two different
  meanings look identical on one card.
- **`itinerary-timeline` (M4)** has a shape waiting for it: `get_distances_pairwise` on
  `services/distance_matrix.py` batches independent legs by shared origin only and never into a
  dense grid — an N-leg itinerary costs N elements, not N². `route_cache` is its own table and
  its own feature; do not extend `distance_cache` for legs.
- **Ops, before real use** (`architecture.md`, and Phase 11 of this checklist): quota caps at
  the free-tier thresholds, a billing alert, the **server** key restricted by IP and the browser
  key by HTTP referrer — two separate keys. The app degrades to estimates everywhere with no
  key at all, which is deliberate but is not a substitute for the caps.
