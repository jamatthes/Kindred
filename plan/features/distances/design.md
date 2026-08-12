# distances — Design

Implements `requirements.md` in this directory. Read `plan/architecture.md` (especially the
Google API usage table and cost rules) and `plan/design-system.md` first.

---

## HARD INVARIANT — never call Google in a render path

From `CLAUDE.md` and `plan/architecture.md`. This feature is the main place that rule could be
broken, so it is restated concretely:

1. A request serving a page, a list, a card, or a panel **never** calls Distance Matrix. It
   reads `distance_cache`, and falls back to a haversine value computed in SQL.
2. Distance Matrix is called **only** from a FastAPI background task in
   `server/app/services/distances.py`, triggered by a small, closed set of events listed below.
3. A (family, suggestion) pair is computed **once** and cached forever. It is recomputed only
   when the pin moves beyond the epsilon or the family's home changes.
4. In the **End** stage no external call is made at all.

---

## Data model

### `distance_cache` (exists in `architecture.md`, two PROPOSED ADDITIONS)

| Column | Use here |
|---|---|
| `id` | uuid pk |
| `family_id` | FK, part of the unique pair |
| `suggestion_id` | FK, part of the unique pair |
| `duration_s` | driving seconds; nullable when no route exists |
| `distance_m` | driving metres; nullable when no route exists |
| `mode` | always `driving` in v1 |
| `computed_at` | when the value was obtained |
| `created_at` / `updated_at` | standard |

Unique constraint on `(family_id, suggestion_id)` — the pair is the identity, and the upsert
depends on it.

**PROPOSED ADDITION — `distance_cache.status`** (varchar, not null, default `pending`).
Values: `pending` / `ok` / `no_route` / `failed`.

Rationale: `architecture.md` gives `distance_cache` no way to record a *negative* result. With
only nullable `duration_s`, a pair that genuinely has no driving route — a home in the UK and a
suggestion on a Greek island, a ferry-only crossing, an ocean between them — is
indistinguishable from a pair that has not been computed yet. Every list render would see a
null, conclude "not computed", and re-queue the task, calling Distance Matrix forever for a
pair that will never resolve. `status` makes the negative result a real, cacheable answer.

**PROPOSED ADDITION — `distance_cache.attempts`** (int, not null, default 0).

Rationale: transient failures (quota exhaustion, a timeout, a 5xx) must be retried, but not
indefinitely. `attempts` bounds the retry loop. Once it reaches the cap (target 3), the row
settles at `failed` and is left alone until the main admin's explicit force-recompute. Without
it, a bad afternoon at the API turns into an unbounded retry storm against a paid endpoint.

Both additions are small, additive, and default-safe on existing rows.

### `families` (read-only here)

`home_lat`, `home_lng`, `home_geocoded_at` supply the origins. A family with a null
`home_lat`/`home_lng` is not sent to Distance Matrix and is reported to the UI as
"home address not set yet" rather than being silently dropped.

### `suggestions` (read-only here)

`lat`/`lng` supply the destination. For `type = 'region'` these already hold the geometry
centroid — `map-suggestions` computes and stores it on write, so this feature needs no special
case. NOTE: measuring to a region's centroid is an approximation by nature; a large region's
edge may be materially closer. The UI labels region distances as "to the centre of" so the
approximation is stated rather than implied.

---

## The batching strategy

Distance Matrix accepts multiple origins and multiple destinations in one call and bills per
origin-destination *element*. Element count is what matters, so the win is in round trips and
latency rather than raw cost — but fewer, well-shaped calls also make quota behaviour far
easier to reason about.

### On suggestion create or move — one call

**Origins:** every family in the trip with a geocoded home.
**Destination:** the single suggestion.

One call covers the whole trip's worth of new pairs. With six families that is one request
producing six cached rows. This is the common case and the one the design optimises for.

### On family home change — chunked calls

**Origin:** the one family.
**Destinations:** every suggestion in the trip.

Distance Matrix caps destinations per request (25 at time of writing) and total elements per
request (100), so this is chunked into batches of at most 25 destinations. A trip with 60
suggestions costs three calls for that family. Home changes are rare, so this is acceptable.

### Chunking rules
- Never exceed the documented per-request origin, destination, and element limits; keep the
  limits as named settings in `core/config.py`, not literals scattered through the service.
- Chunk boundaries are deterministic (ordered by suggestion `created_at`) so a retry re-issues
  the same chunks rather than a fresh random split.
- A chunk that fails does not fail its siblings — each chunk's rows are upserted independently.

### Trigger list (exhaustive)
| Trigger | Shape | Source |
|---|---|---|
| Suggestion created | 1 call, all homes → new suggestion | `map-suggestions` POST |
| Suggestion moved > epsilon (25 m) | 1 call, all homes → moved suggestion | `map-suggestions` PATCH |
| Family home geocoded or changed | chunked, that home → all suggestions | `families` |
| Family created with a home | chunked, that home → all suggestions | `families` |
| Main admin force-recompute | scoped to a suggestion or the trip | this feature |

Nothing else queues a call. In particular: opening a card, loading the list, sorting, filtering,
reconnecting a WebSocket, and any read whatsoever queue nothing.

---

## Haversine fallback

Computed in SQL on every read where a cached `ok` row is absent, using the shared
`haversine_m` expression helper (`server/app/models/geo.py`, introduced by `map-suggestions`).

- Returned as `distance_m` with `is_estimate: true` and **no** `duration_s` — inventing a
  driving duration from a straight line would be dishonest, and `design-system.md`'s honesty
  rules apply to numbers on cards just as much as to charts.
- The UI renders an estimate as a distance only ("~48 km away, driving time pending").
- Estimates are never written to `distance_cache`. The cache holds real answers only.

---

## REST endpoints

All under `/api/v1`, session auth, Pydantic schemas both directions.

### `GET /api/v1/suggestions/{id}/distances`
Every family's distance for one suggestion.

Response:
```
{ suggestion_id,
  distances: [ { family_id, family_name, family_color,
                 status,            // ok | pending | no_route | failed | no_home
                 duration_s | null,
                 distance_m,
                 is_estimate,       // true when the value is haversine
                 computed_at | null } ] }
```
Ordered with the calling user's own family first. Families without a geocoded home appear with
`status: no_home`. Permission: `require_member`. Available in every stage.

### `GET /api/v1/distances`
Bulk form for the list view, so rendering fifty rows costs one request.
Query: `trip_id` (required), `suggestion_ids[]` (optional; defaults to the whole trip),
`family_id` (optional; defaults to the caller's family — restricts the response to one family's
values for a lighter payload).
Response: a map of `suggestion_id → distances[]` in the shape above.
Permission: `require_member`.

NOTE: `map-suggestions`' `GET /api/v1/suggestions` already embeds a `distances` array per item
for exactly this reason. This endpoint exists for the case where the client needs to re-fetch
distances alone — for example after switching the sort to another family's perspective.

### `POST /api/v1/distances/recompute`
Request: `{ trip_id, suggestion_id? }` — omit `suggestion_id` to recompute the whole trip.
Response: `{ queued_pairs, estimated_api_calls }`, returned **before** the work runs so the UI
can state the cost.
Permission: `require_main_admin`. Stage: `require_stage("planning", "holiday")` — explicitly
rejected in End.
Behaviour: resets matching rows to `pending` with `attempts = 0`, including rows currently at
`no_route` or `failed`, then queues the background task. This is the only path that retries a
settled negative result.

---

## WebSocket events

### Emitted
| Event | Payload | When |
|---|---|---|
| `distance.updated` | `suggestion_id, family_id, status, duration_s, distance_m, is_estimate: false, computed_at` | a cached row is written |

Emitted per row rather than per batch, so a chip swaps from estimate to real value as soon as
its own answer lands rather than waiting for the slowest sibling.

### Consumed
| Event | Effect |
|---|---|
| `suggestion.created` | render the new row with an estimate immediately |
| `suggestion.moved` | revert the affected chips to the estimate state pending recomputation |
| `suggestion.deleted` | drop cached rows from client state |

---

## Background task

Lives in `server/app/services/distances.py`, wrapped behind an interface so tests fake it and
never touch Google (per `architecture.md`'s testing strategy).

> **NOTE (added under the M3-services pre-build brief) — `DistanceMatrixService` is pre-built,
> route-free and DB-free.** `server/app/services/distances.py` already exists, following the
> same isolation pattern as `link_preview.py` and `boundaries.py`: it knows nothing about
> `distance_cache`, `families`, or `suggestions`, only about (lat, lng) pairs. The M3 feature
> agent's job is to write the *thin* layer around it — `queue_for_suggestion`,
> `queue_for_family`, `recompute` — that resolves DB rows into `LatLng`s, calls the three
> methods below, and maps `ElementResult.status` onto `distance_cache.status`/`attempts` per
> the table under "Flow" (this service has no `attempts` column to increment; that policy
> belongs to the DB layer, not the Google-calling layer).
>
> Public shape actually built (the design above described the batching *strategy* but not a
> method-level API, so this fixes that as three methods rather than one grid call):
> - `get_distances_many_to_one(origins, destination, mode) -> list[ElementResult]` — the
>   suggestion create/move shape (all homes -> one suggestion), chunked at 25 origins.
> - `get_distances_one_to_many(origin, destinations, mode) -> list[ElementResult]` — the home
>   change shape (one home -> all suggestions), chunked at 25 destinations.
> - `get_distances_pairwise(pairs, mode) -> list[ElementResult]` — added for
>   `itinerary-timeline`'s future route-leg use (not this feature's DB writes): independent
>   (origin, destination) pairs, grouped by shared origin only, **never** forced into a dense
>   grid — an itinerary with no repeated leg origins costs exactly one element per leg, which a
>   naive full-grid batch would multiply by the leg count.
>
> `ElementResult.status` is `"ok" | "not_found" | "zero_results"` — a narrower vocabulary than
> `distance_cache.status`'s four values, deliberately: this service has no concept of `pending`
> (that is a DB row state before any call happens) or a capped `attempts` counter (`failed` is
> reached by *this feature's* retry-budget policy, not by the Google client). The DB layer maps
> `ok` -> `ok`, `zero_results` -> `no_route` (cached permanently, per this file's own rule), and
> `not_found` -> either a retry or `failed` depending on `attempts`.
>
> **Caching is a bounded in-memory TTL cache by default (`InMemoryTtlCache`, ~1h), not the
> forever-cache this file specifies.** The service accepts any `CacheProtocol` (`get`/`set` with
> a TTL); the M3 agent should inject a `distance_cache`-backed implementation whose `get()`
> treats any row already `status = ok` or `status = no_route` as an unconditional, non-expiring
> hit — the default TTL cache exists only to stop one logical chunked batch from re-asking
> Google for a pair two chunks already resolved, not to serve as the permanent cache itself.
> Quota/auth failures (`REQUEST_DENIED`, `OVER_QUERY_LIMIT`, etc.) raise typed exceptions
> (`DistanceServiceAuthError`, `DistanceServiceQuotaError`) rather than degrading a row — the DB
> layer should catch these around a chunk and treat the whole chunk as failed/degraded (banner
> case in "UI behaviour" > "Degraded mode"), not retry chunk-by-chunk into further quota spend.
> Rationale and full contract in the module docstring of `distances.py`.

Flow:
1. Resolve the work set into (family, suggestion) pairs, skipping families with no geocoded home.
2. Upsert `pending` rows for pairs not already `ok`, so a concurrent read shows "pending" rather
   than nothing.
3. Shape the calls per the batching strategy; respect origin/destination/element caps.
4. Issue the call with a timeout and bounded retry.
5. Map each element's status onto a row:
   - `OK` → `status = ok`, store `duration_s` and `distance_m`, set `computed_at`.
   - `ZERO_RESULTS` → `status = no_route`, null duration and distance. **Cached permanently** —
     this is the answer, not a failure.
   - `NOT_FOUND` → `status = failed`, increment `attempts` (bad coordinates; worth one retry).
   - Transport error, timeout, `OVER_QUERY_LIMIT`, or 5xx → increment `attempts`; re-queue with
     exponential backoff while `attempts` is below the cap, otherwise settle at `failed`.
6. Emit `distance.updated` per written row.
7. Never raise into the request that queued it — a failed distance must not fail a suggestion
   creation. The suggestion is the user's work; the distance is a convenience.

Concurrency: an advisory lock or a `pending` guard prevents two overlapping tasks from
duplicating calls for the same pair, which is the realistic way this feature would leak budget.

---

## UI behaviour

### Distance chips
- Format: duration first, then the origin — "2h 40m from Parkers". Duration is what people
  plan around. Under an hour reads as "35m from Parkers".
- Estimate state: distance only, visually muted, with an explicit approximation marker —
  "~48 km from Parkers · driving time pending". A tooltip explains that a straight-line estimate
  is shown until the driving time is calculated.
- `no_route`: "No driving route from Parkers", with a tooltip noting a ferry or flight may be
  needed. Rendered as information, not as an error.
- `failed`: "Distance unavailable", quiet, with the main admin additionally seeing a retry
  affordance that calls the recompute endpoint.
- `no_home`: "Home address not set" — actionable for that family's admin, who gets a link to
  set it.
- Region destinations append "to the centre of" in the tooltip so the centroid approximation is
  stated.

### Placement
- **Popover card** — the caller's own family chip only. Cards stay glanceable per
  `design-system.md`.
- **Side panel / bottom sheet** — own family first, then an expander revealing every family,
  each row carrying the family colour accent from the `--family-1…8` slots.
- **List row** — own family's value in the distance column, right-aligned with tabular figures
  per the data-table pattern.

### Sorting
- Distance is one of the tri-state sort columns (asc → desc → original) in the suggestion list.
- Sort uses the caller's own family by default; a selector switches the perspective to another
  family, and the column header states whose perspective is active so a sorted list is never
  ambiguous.
- Ordering: real values ascending, then estimates (marked), then `failed`/`no_home`, then
  `no_route` last. A suggestion nobody can drive to belongs at the bottom.

### Colour and honesty
Colour never carries the meaning alone — every state pairs with text and an icon, per the
accessibility baseline. Distance is deliberately **not** tinted with the preference ramp:
that ramp means "how much the group likes this", and reusing it for "how far away this is"
would make two different meanings look identical on one card.

### Loading
Chips never show a spinner. An estimate is a real number and renders immediately; it simply
sharpens when the driving value arrives. The transition is a 150–250 ms crossfade, suppressed
under `prefers-reduced-motion`.

---

## Edge cases and error states

| Case | Handling |
|---|---|
| Family home not geocoded yet | Excluded from the API call entirely; reported as `no_home`. Once `families` geocodes it, the home-change trigger fills in every pair. |
| Suggestion created before any family has a home | No call is made; rows stay absent and reads show estimates. The first geocoded home backfills. |
| Genuinely unroutable pair (island, overseas) | `ZERO_RESULTS` → `no_route`, cached permanently. Never retried automatically. This is the single most important case the `status` column exists for. |
| Pin nudged a few metres | Below the 25 m epsilon, no recompute is queued. Shared with `map-suggestions`, which owns the epsilon check. |
| Pin moved far | Existing rows for that suggestion reset to `pending`; chips revert to estimates; one call re-fills them. |
| Home changed | Only that family's rows reset. Other families' cached values are untouched. |
| Quota exhausted | Rows increment `attempts` and settle at `failed` after the cap; the UI degrades to estimates everywhere. The main admin sees a banner explaining that the distance service is unavailable and that estimates are being shown. |
| API key missing or misconfigured | Same degraded path — estimates only, admin banner. The trip stays fully usable; distances are an enhancement, not a dependency. |
| Distance Matrix returns a partial result | Each element is mapped independently; successful elements cache normally and failures retry on their own. |
| Two overlapping recompute tasks | Advisory lock / `pending` guard ensures one call per pair. |
| Suggestion deleted mid-computation | The upsert finds no suggestion and discards the result; the cascade from `map-suggestions` removes any rows already written. |
| Family deleted | Its `distance_cache` rows cascade away with it. |
| End stage reached with pairs still pending | Those pairs stay pending forever and render as estimates. No call is made in End, including force-recompute, which returns the stage guard's rejection. |
| Force-recompute on a large trip | The response states `estimated_api_calls` before running so the admin sees the cost; a trip with 60 suggestions and 6 families is roughly 6 chunked calls, not 360. |
| Clock skew / very old `computed_at` | Values are never expired by age. A driving distance between two fixed points does not change; that is the premise of caching forever. Only a move or a home change invalidates. |

---

## NOTE (2026-08-12) — handoff from `map-suggestions`'s M3 web implementation

`SuggestionDetailPanel.tsx` and `SuggestionsList.tsx` (`web/src/features/map-suggestions/`)
already render `Suggestion.distances` (the array `design.md`'s `GET /suggestions` response
shape defines): the detail panel lists every family's duration with an "(estimate)" suffix
when `is_estimate`, and the list's Distance column takes the minimum `distance_m` across
families for sorting. Nothing here computes a distance — it is pure display of whatever the
server denormalises into the suggestion response, per this feature's cost/caching rules.
`suggestion.moved`'s re-queue and `distance.updated`'s WS event are already consumed
(`useSuggestions.ts`) by refetching the single affected suggestion, since this feature's
event payload contract was not fixed at the time `map-suggestions`'s web layer was built —
confirm the shape once this feature lands and simplify to a direct patch if it turns out to
carry the recomputed value inline.

---

## NOTE (2026-08-12) — distances M3 web implementation, deviations from this doc

Built in `web/src/features/distances/` against typed fixtures — still no backend in this
worktree. Resolved the map-suggestions handoff note above (`distance.updated` now patches
the specific family row in place in `useSuggestions.ts`, and `suggestion.moved` now reverts
that suggestion's real rows to `pending`/estimate locally, both directly tested). Full
reasoning for every item below is inline in `tasks.md` next to its checklist box.

- **`SuggestionDistance` (the pre-existing, narrower type `map-suggestions` defined on
  `Suggestion.distances`) is now this feature's own `DistanceOut`.** The two docs describe
  the same per-family row; keeping two parallel shapes would have meant every consumer
  guessing which was authoritative. `Suggestion.distances: DistanceOut[]` now carries
  `status`/`family_color` too, matching what this doc's `GET /suggestions/{id}/distances`
  already specified.
- **The list row is plain tabular text (`DistanceCell`), not the full `DistanceChip`.**
  `design.md`'s "Placement" section says "own family's value ... right-aligned with tabular
  figures per the data-table pattern" — the same wording every other numeric column
  (votes, comments) uses, and those render as plain text too. The full chip's icon and
  tooltip have no room in a table cell and would be the only decorated cell in the row.
- **No dedicated distance-service health endpoint.** The degraded-mode banner
  (`DistancesSection.tsx`) is a client-side heuristic (`useDistanceHealth.ts`) over
  `GET /distances?family_id=<admin's own>` — more than `MIN_SAMPLE` (3) pairs attempted and
  more than 30% settled `failed`. This doc's REST section has no aggregate health route; a
  real one (e.g. counting `failed` rows trip-wide, not just one family's) would be more
  accurate and is a reasonable follow-up once the backend exists to design it against.
- **"States the cost before running" has no separate preview call.** `POST
  /distances/recompute`'s own response carries `queued_pairs`/`estimated_api_calls`
  *before the background Google calls run* — this pass shows that response as a toast the
  instant it arrives rather than adding a two-step "preview, then confirm" flow the
  contract doesn't define. `useRecompute.ts` states this reasoning inline.
- **A failed chip's per-row "Retry" and the panel's "Force recompute this suggestion"
  button call the identical endpoint.** The recompute endpoint has no per-family
  granularity (`{trip_id, suggestion_id?}` only), so a retry on one family's chip
  necessarily recomputes every family's pair for that suggestion. Both affordances are
  kept because the chip-level one is more discoverable at the point of failure and the
  panel-level one is what Phase 11 explicitly asks for; they are not two different actions.
- **`plan/architecture.md`'s `distance_cache.status`/`.attempts` update is deferred** — this
  pass is web-only against a documented contract; the backend agent owns that table's real
  schema and its docs.

