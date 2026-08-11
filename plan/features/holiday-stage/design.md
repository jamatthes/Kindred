# holiday-stage — Design

**Read first:** `plan/overview.md`, `plan/architecture.md`, `plan/design-system.md`, `CLAUDE.md`,
and this feature's `requirements.md`.

> NOTE: role hierarchy updated 2026-08-11 — stage transitions are now owner-or-organiser
> (`require_organiser`), not "main admin". Family-level location-sharing switches are set by a
> **head of family** or a **spouse** (`family_members.role`), not a "family admin", with one
> asymmetry: a spouse cannot flip the head's own per-member switch. See `plan/overview.md`'s
> Roles section and `requirements.md`'s HS-15.

## Data model

All tables below already exist in `plan/architecture.md`. No new tables are required.

| Table | Columns used | Notes |
|---|---|---|
| `trips` | `id`, `stage` (`planning`/`holiday`/`end`), `start_date`, `end_date`, `owner_user_id`, `timezone` | `owner_user_id` is the owner. `timezone` drives all "now" calculations — never use server local time. |
| `itinerary_items` | `trip_id`, `day`, `start_time`, `end_time`, `title`, `suggestion_id`, `sort` | Source for now/next. Times are nullable, which the now/next algorithm must handle. |
| `checkins` | `trip_id`, `user_id`, `lat`, `lng`, `accuracy_m`, `note`, `created_at` | One row per deliberate check-in. "Running late" is just a `note` value. |
| `live_locations` | `user_id` (unique), `trip_id`, `lat`, `lng`, `accuracy_m`, `updated_at` | Exactly one row per user. Upserted by foreground `watchPosition`; **deleted** on toggle-off. Never accumulates history. |
| `user_settings` | `user_id`, `live_location_enabled` (default false), `push_enabled` | The member's own consent. Seeded from their family's default when they join; written by nobody but that member afterwards. |
| `families` | `color`, `location_sharing_allowed`, `member_location_default` | `color` drives pin colour for check-ins and live markers. The two policy columns are read on every live-location query and are owned by `families` (FM-15) — this feature never writes them. |
| `family_members` | `location_sharing_allowed` | The family's head (or spouse) per-member veto. Read-only here, same as above. |
| `users` | `first_name`, `last_name`, `display_name`, `avatar_attachment_id` | Marker badge and hover label. `initials` and `avatar_thumb_url` are served pre-computed by `families`' serialiser so every surface renders one identity. |
| `attachments` | `subject_type='checkin'`, `subject_id`, `uploader_id`, file path, `mime`, `width/height` | Check-in photos, and the archive photo grid. |
| `notifications` | `recipient_user_id`, `type`, `payload_json`, `read_at` | Stage changes and check-ins generate rows; see `plan/features/notifications/`. |

### Derived values (not stored)

- **Staleness of a live location** — computed from `updated_at`. Two thresholds, defined as server
  config constants: `LIVE_STALE_AFTER` (default 2 minutes → render as stale) and `LIVE_DROP_AFTER`
  (default 10 minutes → omit from the API response and delete the row on next sweep). Storing a
  status column would just duplicate `updated_at`.
- **"Now" and "next"** — computed per request from `itinerary_items` in the trip's timezone.

### No proposed additions

Every requirement maps onto the existing schema. In particular:

- "Running late" needs no table — it is a `checkins.note` value chosen from a client-side preset list.
- Live-location staleness needs no column — `updated_at` plus thresholds covers it.
- Stage history/audit needs no table in v1 — stage changes generate `notifications` rows, which are
  durable and already carry actor and timestamp in `payload_json`.
  NOTE: if a real audit trail is wanted later, that is an `admin-console` concern, not this feature's.

## Stage machine

```
planning ──advance──▶ holiday ──advance──▶ end
   ▲                     │                  │
   └────── revert ───────┘                  │
                         ◀───── revert ─────┘
```

- Legal advances: `planning→holiday`, `holiday→end`. Anything else is 409.
- Legal reverts: `holiday→planning`, `end→holiday`. Reverting more than one step in a single call
  is not allowed; the owner or organiser can call it twice.
- Transitions are performed in a single transaction that also enqueues notifications and the
  websocket broadcast, so clients never see a half-applied change.

### Side effects of entering `end`

1. All `live_locations` rows for the trip are deleted (sharing cannot be active in a frozen trip).
2. A `location.cleared` event is broadcast for each affected user.
3. Clients receiving `stage.changed` with `stage: "end"` stop any active `watchPosition`.

### Side effects of leaving `end` (revert)

Nothing is restored — no live-location rows are recreated. Members must re-enable sharing themselves.
This is deliberate: reverting a stage must never silently turn someone's location sharing back on.

## Stage guards

Per `plan/architecture.md`, permissions and stage rules live in FastAPI dependencies, never in
frontend logic.

- `require_stage("planning", "holiday")` — attached to **every mutating route in the entire
  application** (suggestions, votes, comments, polls, itinerary, check-ins, live locations). This
  feature owns the dependency; other features import it.
- The single exception is `PATCH /api/v1/trips/{trip_id}/stage`, which must remain callable in
  `end` so a trip can be reverted.
- Guard rejections return **409 Conflict** with a machine-readable body so the UI can render the
  specific inline message required by HS-14:
  ```json
  { "detail": { "code": "stage_forbidden", "stage": "end",
                "message": "This trip is finished and is now read-only." } }
  ```
  NOTE: 409 is used rather than 403 because the refusal is about the trip's state, not the caller's
  identity — this keeps "you lack permission" and "the trip is frozen" distinguishable in the UI.
- Guards read the trip's stage from the database inside the request, never from a client-sent value.

## REST endpoints

All under `/api/v1/`. Session cookie auth + CSRF on mutations, per `plan/architecture.md`.

### Stage

| Method | Path | Request | Response | Dependencies |
|---|---|---|---|---|
| `GET` | `/trips/{trip_id}` | — | `{ id, name, stage, start_date, end_date, timezone }` | `require_member` |
| `PATCH` | `/trips/{trip_id}/stage` | `{ "stage": "holiday", "reason": "revert"? }` | `{ id, stage, changed_at, changed_by }` | `require_organiser` (owner or organiser) — **no stage guard** |

`PATCH .../stage` validates the transition against the machine above. Invalid target → 409
`{code: "illegal_transition"}`. Same-stage no-op → 200 with the unchanged trip (idempotent).
A `reason: "revert"` field is required when moving backwards, so a backwards move can never be an
accidental payload.

### Now / next

| Method | Path | Request | Response | Dependencies |
|---|---|---|---|---|
| `GET` | `/trips/{trip_id}/now-next` | `?at=<iso8601>` (optional, testing) | `{ now: Item\|null, next: Item\|null, next_is_tomorrow: bool, server_time: iso }` | `require_member` |

`Item` = `{ id, title, day, start_time, end_time, lat, lng, place_name, notes, suggestion_id }`.

Algorithm, all in the trip's `timezone`:
1. `now` = the item where `start_time <= t < end_time`. Items with a null `end_time` are treated as
   occupying until the next item's start, or end of day if none follows.
2. `next` = the earliest item today with `start_time > t`. If none, the earliest item on the next
   day that has any items; set `next_is_tomorrow: true`.
3. Items with a null `start_time` sort by `sort` within their day and are never chosen as `now`;
   they can be `next` only if no timed item qualifies.
4. Both null → the client renders the empty state.

### Check-ins

| Method | Path | Request | Response | Dependencies |
|---|---|---|---|---|
| `POST` | `/checkins` | `{ trip_id, lat, lng, accuracy_m, note? }` | `201` `Checkin` | `require_member`, `require_stage("holiday")` |
| `GET` | `/checkins` | `?trip_id=&cursor=&limit=50` | `{ items: Checkin[], next_cursor }` | `require_member` |
| `DELETE` | `/checkins/{id}` | — | `204` | `require_member` + (own check-in, OR owner/organiser for any, OR the check-in author's own head/spouse), `require_stage("planning","holiday")` |

`Checkin` = `{ id, user: {id, display_name}, family: {id, color}, lat, lng, accuracy_m, note, created_at, attachments: [...] }`.

- `lat`/`lng` are validated to real ranges; `accuracy_m` above a sanity threshold (e.g. 5000m) is
  accepted but flagged `low_accuracy: true` in the response so the UI can caption it.
- Rate limited per user (e.g. 1 check-in / 10s) to stop double-tap duplicates.
- Photos attach via the existing attachments upload route with `subject_type='checkin'`; the client
  creates the check-in first, then uploads.
- `GET /checkins` is readable in `end` (archive); only creation and deletion are stage-guarded.

### Live locations

| Method | Path | Request | Response | Dependencies |
|---|---|---|---|---|
| `PUT` | `/live-locations/me` | `{ trip_id, lat, lng, accuracy_m }` | `200 { updated_at }` | `require_member`, `require_stage("holiday")`, requires `user_settings.live_location_enabled = true` |
| `DELETE` | `/live-locations/me` | — | `204` | `require_member` — **no stage guard** (stopping must always work) |
| `GET` | `/live-locations` | `?trip_id=` | `{ items: [{ user, family, lat, lng, accuracy_m, updated_at, stale: bool }] }` | `require_member` |
| `PATCH` | `/users/me/settings` | `{ live_location_enabled: bool }` | updated settings | `require_member` — owned by `foundation`; this feature only consumes it |

- `PUT` is an upsert on the unique `user_id`. If `live_location_enabled` is false the endpoint
  returns 409 `{code: "sharing_disabled"}` — the server is the authority, not the client toggle.
- Setting `live_location_enabled` to false **also deletes the row** in the same transaction. The
  toggle and the data can never disagree.
- `GET` omits rows older than `LIVE_DROP_AFTER` and marks rows older than `LIVE_STALE_AFTER` as
  `stale: true`. It never returns the caller's own row as a "someone else" marker.

`PUT` deliberately does **not** consult the family policy. A member whose family currently hides
them keeps writing their position, and the row is filtered out at read time instead. Two reasons:
the family switch is a live filter that must restore instantly when flipped back, and stopping
the writes would mean a member's indicator said "sharing" while nothing was being stored, which
is the one thing the indicator must never do.

### Who appears in `GET /live-locations`

The response is the set of people the caller may see, computed server-side. The client filters
nothing; it cannot, because it is not sent the rows it may not have.

```sql
-- conceptually, per candidate row
   live_locations.updated_at > now() - LIVE_DROP_AFTER   -- actually sharing, recently
AND user_settings.live_location_enabled                   -- the member's own consent
AND family_members.location_sharing_allowed               -- their family's head/spouse per-member switch
AND families.location_sharing_allowed                     -- their family's head/spouse master switch
AND families.trip_id = <the caller's trip>                -- same trip, always
```

The middle three terms are defined, and their ownership explained, in
`plan/features/families/design.md` under "Location sharing policy". This feature reads them and
writes none of them.

One row is returned per **person**, never per family. A family with four sharing members
produces four rows.

The response tells the caller nothing about *why* somebody is absent. There is no
`hidden_by_policy` flag and no count of suppressed rows, because from outside a family the
difference between "chose not to share", "was hidden by their family's head or spouse" and "phone is in a
pocket" is not the viewer's business — and a field distinguishing them would make the map a way
to audit other people's choices.

The exception is a caller looking at **their own family**, who is entitled to that detail: they
get it from `GET /families/{id}` (`MemberOut.location_sharing_enabled` and
`location_sharing_allowed`), not from this route. Keeping it out of the map query is what makes
the rule above easy to verify — this endpoint has no entitlement branches at all.

`LiveLocationOut` per row:

```
{user: {id, first_name, last_name, display_name, initials, avatar_thumb_url},
 family: {id, name, color},
 lat, lng, accuracy_m, updated_at, stale: bool}
```

`initials` and `avatar_thumb_url` come from `families`' shared serialiser rather than being
recomputed here, so a marker and a member-list row can never disagree about who someone is.

### Archive

| Method | Path | Request | Response | Dependencies |
|---|---|---|---|---|
| `GET` | `/trips/{trip_id}/archive` | — | `{ trip, itinerary: Item[], checkins: Checkin[], photos: Attachment[], routes: RouteCacheEntry[] }` | `require_member` |

Read-only aggregate for the scrapbook view, one request instead of five. Available in any stage
(useful for testing) but only linked from the UI in `end`. Routes come from `route_cache` —
**no Google call happens here**, per the cost rule in `CLAUDE.md`.

## WebSocket events

One socket per session, trip-scoped rooms, per `plan/architecture.md`.

| Event | Payload | Emitted when | Sent to |
|---|---|---|---|
| `stage.changed` | `{ trip_id, stage, previous_stage, changed_by, changed_at, was_revert }` | Stage patch commits | Everyone in the trip room |
| `checkin.created` | `{ checkin: Checkin }` | Check-in created | Everyone in the trip room |
| `checkin.deleted` | `{ id, trip_id }` | Check-in deleted | Everyone in the trip room |
| `location.updated` | `{ user_id, family_id, lat, lng, accuracy_m, updated_at }` | `PUT /live-locations/me` commits | Everyone in the trip room **who may see that user** — the same four terms as `GET /live-locations`, evaluated at broadcast time — **except the sender** |
| `location.cleared` | `{ user_id, trip_id, reason: "toggled_off"\|"stale"\|"stage_end"\|"hidden_by_family" }` | Row deleted, or made invisible by a policy change | Everyone in the trip room |

`location.updated` is the one event in the product with a per-recipient audience. Broadcasting it
to the whole trip room and letting clients filter would put a coordinate the viewer is not
entitled to inside their browser, where the filter is advisory. The room fan-out therefore
evaluates the visibility terms per recipient before sending.

`hidden_by_family` is emitted when a policy change — not the sharer — makes a marker
disappear: `families.location_sharing_allowed` or `family_members.location_sharing_allowed`
going false. The `live_locations` row survives, which is what lets the marker return the moment
the switch goes back on. It is a separate reason from `toggled_off` so a client never reports
"they stopped sharing" when they did no such thing.

Consumed from `families`: `family.updated` and `member.updated`. When either carries a
permission term that has become false, the live layer drops the affected markers without waiting
for a refetch. When one becomes true, nothing is drawn until that person's next
`location.updated` — the client has no coordinate to draw, and inventing a stale one would be
the map lying about where somebody is.

Client behaviour:
- `stage.changed` → update the shell indicator, re-route if the current route is invalid for the new
  stage, stop `watchPosition` if the new stage is not `holiday`, refetch now/next.
- `location.updated` is high-frequency: the map layer coalesces updates into a single animation frame
  rather than re-rendering per event.
- Reconnect uses the resume handshake already specified in `plan/architecture.md`; on resume the
  client refetches `/live-locations` and `/checkins` rather than replaying missed location events.

## Client-side geolocation behaviour

**Secure context is mandatory** — `navigator.geolocation` requires HTTPS. Per
`plan/architecture.md` this is already guaranteed by Cloudflare in front of the origin. In local
development, `http://localhost` also counts as a secure context; any other dev host will fail, and
the UI must say so rather than showing a generic error.

### Check-in (single fix)

```
getCurrentPosition({ enableHighAccuracy: true, timeout: 10000, maximumAge: 0 })
```
One call. Never a watch. Show a determinate "getting your location…" state with the spinner rules
from `design-system.md` (this is a >1s wait, so it uses inline progress with a cancel affordance).

### Live sharing (foreground watch)

```
watchPosition({ enableHighAccuracy: true, timeout: 30000, maximumAge: 15000 })
```
- Started only by an explicit user toggle; never on app load.
- Sends `PUT /live-locations/me` at most every 15 seconds, and only when the position moved more
  than ~25 metres or 60 seconds elapsed. This keeps the write rate trivial.
- `visibilitychange` → hidden: stop the watch, keep the toggle on, and send `DELETE` after a short
  grace period so a quick app-switch does not flap the marker.
- `visibilitychange` → visible (with toggle still on): restart the watch.
- `pagehide` / `beforeunload`: fire `DELETE` via `navigator.sendBeacon` so closing the tab really
  stops sharing.
- The permission state is checked with the Permissions API where available so the UI can show
  "blocked in browser settings" instead of retrying forever.

## UI behaviour

Per `plan/design-system.md`. Tokens only — no raw hex, no magic px. Everything below must work in
both light and dark.

### Stage indicator and controls

- A compact stage chip in the app shell: label plus icon (never colour alone). `planning` uses
  `--color-info`, `holiday` uses `--color-success`, `end` uses a muted neutral surface.
- Stage controls (owner and organisers only) live in the admin/trip screen, not the main nav. "Start holiday" is a primary
  button; "Finish trip" is a primary button with danger-tinted confirm; "Revert stage" is a quiet
  tertiary control placed below a divider.
- Confirm dialogs are modal (a temporary interaction — the one case `design-system.md` permits an
  overlay), state current → target stage, list consequences in at most three bullets, and require
  the explicit verb ("Finish trip") on the confirm button rather than "OK".

### Now / next screen

- Default mobile route during Holiday; on desktop it appears as a card at the top of the itinerary
  view rather than taking over the map.
- Two stacked cards. "Now" uses the heading step of the type ramp (42) for the title; "Next up" uses
  the subheading step (26) and a muted label. Times use tabular figures.
- Each card: title, time range, place name, distance/route affordance that opens the map focused on
  that item. Full-card tap target.
- Skeletons on first load (structural load, per the loading rules); no spinner.
- Empty states are designed, not blank: "Nothing scheduled right now — enjoy yourselves" with the
  next item promoted, and "Nothing left today — first up tomorrow: …".
- Auto-refreshes on window focus and on a low-frequency timer (60s) so the "now" boundary rolls over
  without user action.

### Check-in

- A single prominent button — thumb-reachable on mobile, ≥44px hit target.
- Tap → sheet with: a live-updating "getting your location" state, then the resolved place, a note
  field, preset note chips ("Running late", "On our way", "We're here", "Stopping for food"), an
  optional photo picker, and a Send button.
- Preset chips fill the note field rather than being a separate concept, so the user can edit them.
- Optimistic: the pin appears immediately in a pending style and settles on server confirmation;
  rolls back with an error toast if the POST fails (per the optimistic-UI rule).
- Success is a toast (transient confirmation of your own action). The durable record is the feed
  entry and the notification.

### Map layers

- Check-in pins: family colour fill, check-in icon, initials label. Clustered when dense.
- Live markers: **one per person, never one per family.** The identity badge from
  `plan/features/families/design.md` at the 40px size — profile picture, or initials on a
  neutral fill, ringed in the family's `--family-N` token — sitting on a shape distinct from the
  check-in teardrop, with a pulsing halo and a freshness caption. The pulse respects
  `prefers-reduced-motion` and becomes a static ring when reduced motion is requested.
- The badge is the same component the member list and presence stack use. A person looks
  identical everywhere in the product, which is the point of defining it once.
- Stale markers: reduced opacity **plus** an explicit "last seen 6 min ago" label — never opacity
  alone, per the accessibility baseline.
- A layer toggle lets users hide live markers or check-ins independently.

#### Marker labels and hover

- Hover or keyboard focus shows the person's **full name** — `"{first_name} {last_name}"`,
  falling back to `display_name` when both name parts are empty — in a small tooltip anchored to
  the marker, with the family name on a second line and the freshness caption beneath.
- The tooltip is rendered from the same tokens as the rest of the product and is never
  colour-only: the family is named in words, not just carried by the ring.
- Markers are reachable by keyboard. Tab moves between them in a stable order (family, then
  name), and focus shows the same tooltip hover does — this is the accessible equivalent, not
  an afterthought.
- On touch there is no hover: the first tap shows the tooltip, a second opens the side panel or
  sheet. A single tap never jumps straight to a panel, because the cheap question ("who is
  that?") should not cost a navigation.
- The tooltip has `aria-describedby` wiring so a screen reader announces the name, family and
  freshness together rather than reading a bare marker.

#### Clustering

- Live markers cluster when they overlap, which on a family trip is the normal case — a family
  in one restaurant is four markers within metres.
- A cluster shows the count and the family rings it contains, so "three of us and one of them"
  is legible before opening it.
- Opening a cluster lists the people inside by full name with their badges, in the side panel on
  desktop and the sheet on mobile. Names, not a pile of circles.
- Live markers and check-in pins cluster separately. They answer different questions and merging
  them would produce a count that means nothing.

### Sharing indicator

- While sharing is active, a persistent bar/chip in the app shell reads "Sharing your location" with
  a stop action. It is not dismissible — it disappears only when sharing stops.
- It uses `--color-info` surface treatment with an icon, and is announced to screen readers via a
  polite live region when it appears and disappears.
- **When the member's family policy is currently hiding them, the indicator says so** — "Sharing
  your location — your family's settings are hiding you from the map right now" — with the stop
  action unchanged. The indicator's entire job is to never overstate what is being shared, and
  a member whose position is being stored but not shown deserves to know both halves.

### First-run disclosure for a seeded-on member

A member whose `live_location_enabled` was seeded `true` from their family's default
(`plan/features/families/`, FM-15) has not yet been asked anything. Before the first
`watchPosition` call of their first session, a single sheet appears:

- The settings copy below, verbatim — the same words as the settings screen, so nobody is asked
  to agree to a summary of something they will later read differently.
- One line naming the source: "Your family's head (or spouse) set sharing to start on for new
  members."
- `Start sharing` and `Not now`. `Not now` writes `live_location_enabled = false` — recorded as
  the member's own setting, indistinguishable afterwards from having turned it off themselves.
- Dismissing the sheet without choosing counts as `Not now`. The safe default when someone walks
  away from a privacy question is not to share.
- It appears once. Having chosen, the member manages it from their profile like anyone else.

This sheet is why a seeded default is not a consent: the browser's permission prompt and this
disclosure both stand between the family head's (or spouse's) setting and any coordinate
leaving the device.

### Settings copy (exact intent, wording to be finalised in DesignSync)

> **Share my live location during the trip** — Off by default.
> Your family can see where you are only while Kindred is open on your screen. Close the app or
> switch to another app and sharing stops on its own. Kindred cannot track you in the background,
> and we don't store a history of where you've been.

### Archive view

- Three-region layout on desktop, following the standard shape: map centre, itinerary/day list in the
  side panel, timeline along the bottom. Mobile stacks them behind a tab bar.
- Photo grid pulls from `attachments` across suggestions and check-ins.
- Every control that would mutate is **absent**, not merely disabled — a disabled button implies
  "later", and there is no later.
- A single banner explains the trip is finished and read-only.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| Geolocation permission denied | Inline message: "Kindred needs location permission to check in", plus a link to browser-specific instructions. The toggle reverts to off. Never retried automatically. |
| Geolocation times out | "Couldn't get a location fix — try moving somewhere with a clearer view of the sky." Retry button. |
| Geolocation unavailable (no HTTPS, unsupported browser) | Feature is hidden with an explanation, not a broken button. |
| Very poor accuracy (>1km) | Check-in still accepted, pin drawn with an accuracy circle, feed entry captioned "approximate location". |
| Two check-ins within the rate limit | Second returns 429; UI treats it as a duplicate tap and shows nothing (the first already succeeded). |
| Live-location `PUT` while `live_location_enabled` is false | 409 `sharing_disabled`; client stops the watch and syncs its toggle from the server. |
| Live-location `PUT` after stage moved to `end` | 409 `stage_forbidden`; client stops the watch. |
| Live-location `PUT` while the family policy hides the sharer | Accepted and stored. The row is filtered at read time, not at write time, so flipping the switch back restores the marker instantly. The sharer's indicator says they are currently hidden. |
| Family switch turned off while members are sharing | Every affected marker is removed for every viewer via `location.cleared` with reason `hidden_by_family`. The `live_locations` rows survive; no `user_settings` row is touched. |
| Family switch turned back on | Markers reappear as each sharer's next `location.updated` arrives — up to one throttle interval. Nothing stale is drawn in the meantime. |
| Per-member switch toggled | Identical behaviour, scoped to that one person. |
| A member's family is deleted while they are sharing | They have no `family_members` row, so no marker: the visibility rule fails on a missing row rather than erroring. Their own toggle is untouched. |
| Marker for a member with no profile picture | Initials badge on a neutral fill with the family ring. Not a placeholder or a silhouette — the initials are the design, not a fallback. |
| Member has no first or last name recorded | Cannot occur for accounts created after `families` ships (both are collected at registration); any legacy row falls back to `display_name` for both the badge and the hover label. |
| Avatar image 404s or fails to decode in the browser | The badge renders initials. A marker never shows a broken-image glyph. |
| Two markers at identical coordinates | They cluster; the cluster lists both by full name. Neither is hidden behind the other. |
| Hovering a marker that disappears mid-hover (stale, or policy change) | The tooltip closes with the marker. No orphaned tooltip is left anchored to nothing. |
| Seeded-on member dismisses the first-run sheet without choosing | Treated as `Not now`; `live_location_enabled` is set false. Sharing never starts from an unanswered question. |
| Seeded-on member denies the browser permission prompt | Their toggle reverts to off with the standard permission-denied message. The family default is not re-applied on the next session — it seeds once. |
| User closes tab without `sendBeacon` firing | Row goes stale after `LIVE_STALE_AFTER`, is hidden after `LIVE_DROP_AFTER`, and is deleted by a periodic sweep task. |
| Websocket disconnected during Holiday | Client shows a subtle "reconnecting" state; on reconnect it refetches check-ins and live locations rather than trusting local state. |
| Stage advanced while a member has an unsaved suggestion form open | Their submit returns 409 `stage_forbidden` with the specific message; the draft is preserved client-side so nothing is lost. |
| The owner and an organiser (or two organisers) press "Start holiday" simultaneously | The transition is idempotent — the second call sees the trip already in `holiday` and returns 200 without a second notification. |
| Revert requested from `planning` | 409 `illegal_transition`. |
| Now/next requested with an empty itinerary | Both slots null; UI shows the empty state pointing at the itinerary. |
| Trip timezone unset | Fall back to UTC and surface an admin warning — do not silently use server time. |
| Check-in deleted while its detail sheet is open | `checkin.deleted` closes the sheet with a brief explanation. |
| Archive requested during `planning` | Endpoint works but returns mostly-empty collections; UI does not link to it. |
