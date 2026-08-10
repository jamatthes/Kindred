# distances — Requirements

Feature 7 in `plan/overview.md`. Milestone M3.

Driving distance and time from each family's home to each suggestion, computed once and cached
forever. This is the quiet feature that makes the map argument-free: when one family lives
three hours further from a cottage than everyone else, that fact should be visible on the card
rather than discovered the week before departure.

## Concepts

- **Origin** — a family's home, geocoded once into `families.home_lat/home_lng` by the
  `families` feature.
- **Destination** — a suggestion's point. For a region, the centroid of its geometry.
- **Pair** — one (family, suggestion) combination. Each pair is computed **once** and cached
  permanently, per the API cost rule in `plan/overview.md`.
- **Estimate** — a straight-line haversine distance computed instantly in SQL, shown while the
  real driving value is pending.

## User stories

### D1 — See how far a suggestion is from my home
**As a member, I can see the driving time from my family's home to any suggestion.**
- A distance chip reads like "2h 40m from Parkers" — duration first, because duration is what
  people actually care about on a drive.
- The chip appears on the popover card and in the side panel.
- My own family's distance is shown by default, without any interaction.

### D2 — See a value immediately, even before the real one exists
**As a member, I never wait on a blank space for a distance.**
- A haversine straight-line estimate renders instantly when no cached driving value exists yet.
- The estimate is visually distinct from a real value and labelled as approximate, so nobody
  plans around it believing it is a driving time.
- When the real value arrives it replaces the estimate live, with no refresh.

### D3 — Compare across all families
**As a member, I can expand a suggestion to see the driving time for every family.**
- The side panel lists every family with a geocoded home, own family first.
- Families whose home is not yet geocoded are listed as such rather than omitted — an absent
  row would read as "no distance" when the truth is "we don't know your address yet".
- This is deliberately open to all members: fairness arguments need shared data.

### D4 — Sort suggestions by distance
**As a member, I can sort the suggestion list by driving time.**
- Sorting uses my own family's distances by default.
- I can switch the sort to another family's perspective ("sort by distance from the Hendersons").
- Suggestions with only an estimate sort by that estimate and stay marked as approximate.
- Suggestions with no route at all sort to the end.

### D5 — Distances follow the pin
**As a member, when I move a suggestion's pin, its distances update.**
- Moving a pin beyond a small threshold recomputes every family's distance for that suggestion.
- A trivial nudge does not trigger recomputation — this protects the API budget from jitter.
- The chip returns to its estimate state while the new value is being fetched.

### D6 — Distances follow the home address
**As a family admin, when I correct my family's home address, our distances update everywhere.**
- Changing and re-geocoding a home invalidates and recomputes that family's cached pairs.
- Other families' cached values are untouched.
- The change is visible across the trip without anyone re-loading.

### D7 — Force a recompute
**As the main admin, I can force a recompute when something has clearly gone wrong.**
- Available for a single suggestion or for the whole trip.
- The action states how many API calls it will cost before running, because the whole design
  exists to keep that number small.
- Pairs marked as permanently unroutable are retried by this action — it is the escape hatch.

## Permissions

| Action | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| See own family's distances | Yes | Yes | Yes | No |
| See all families' distances | Yes | Yes | Yes | No |
| Sort by any family's distance | Yes | Yes | Yes | No |
| Trigger recompute implicitly (create/move a suggestion) | Yes | Yes | Yes | No |
| Trigger recompute implicitly (change own family's home) | Yes | Yes | No | No |
| Force recompute for a suggestion or trip | Yes | No | No | No |

There is no member-facing write endpoint. Distances are a consequence of other actions, never
something a user sets directly. Recomputation is triggered by suggestion and home mutations,
which carry their own permission checks in `map-suggestions` and `families`.

All members can see all families' distances. NOTE: this is a deliberate transparency choice
consistent with attributed voting in `voting-comments` — a group deciding together needs the
same numbers in front of everyone.

## Stage availability

| Stage | Behaviour |
|---|---|
| **Planning** | Full behaviour. New and moved suggestions queue Distance Matrix calls; homes geocode and recompute. |
| **Holiday** | Unchanged — suggestions still arrive during the trip and still need distances. |
| **End** | Read-only. Cached values and estimates are served normally as part of the archive. **No external API call is made in the End stage under any circumstance**, including the main admin's force-recompute, which is rejected by the stage guard. |

## Out of scope (v1)

- Transit, walking, cycling, or any mode other than `driving`. `distance_cache.mode` exists
  and is always `driving` in v1; the column leaves the door open.
- Traffic-aware or departure-time-specific estimates. A cached value that changes by the hour
  would defeat the cache-forever rule that keeps this inside the free tier.
- Distances **between** suggestions — that is `route_cache` and belongs to
  `itinerary-timeline`.
- Per-user origins. The origin is the family home; individuals do not get their own.
- Multiple homes per family (a family with two households is out of scope; they can create two
  families if needed).
- Turn-by-turn directions or a route polyline for the home→suggestion leg. Only duration and
  distance are stored; drawn routes belong to the itinerary.
- Toll, fuel, or cost estimation.
- Historical tracking of how a distance changed over time.
- Automatic retry of unroutable pairs on a schedule — retries are bounded and then require the
  admin's explicit force-recompute.
