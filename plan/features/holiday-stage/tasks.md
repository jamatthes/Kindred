# holiday-stage — Tasks

**Read first:** this feature's `requirements.md` and `design.md`, plus `plan/architecture.md` and
`plan/design-system.md`. Milestone **M5** (archive polish continues into M7).

Assumes `foundation` (auth, sessions, trips, websocket shell), `map-suggestions`,
`voting-comments`, and `itinerary-timeline` are already implemented.

---

## Phase 1 — Stage guard infrastructure

- [ ] Add `LIVE_STALE_AFTER_SECONDS` (120) and `LIVE_DROP_AFTER_SECONDS` (600) to
      `server/app/core/config.py`.
- [ ] Create `require_stage(*allowed)` dependency factory in `server/app/deps.py`; it loads the trip
      referenced by the request, compares `trips.stage`, and raises 409 with
      `{code, stage, message}` on mismatch.
- [ ] Add a `StageForbidden` exception + handler that produces the documented JSON body.
- [ ] Apply `require_stage("planning", "holiday")` to every existing mutating route: suggestions,
      suggestion votes, comments, polls, poll scores, itinerary items, families, invites.
- [ ] Confirm no read route and no auth route got a stage guard by mistake.

**Verify:** `pytest server/tests/test_stage_guard.py -q` — parametrised test asserting every mutating
route returns 409 `stage_forbidden` when the trip is in `end`, and 2xx when in `planning`.

---

## Phase 2 — Stage machine endpoint

- [ ] Add a `StageTransition` service in `server/app/services/stage.py` encoding the legal
      advance/revert transitions and rejecting anything else.
- [ ] Add Pydantic schemas `StageChangeRequest { stage, reason? }` and `StageChangeResponse`.
- [ ] Add `PATCH /api/v1/trips/{trip_id}/stage` to the trips router with `require_main_admin` and
      **no** stage guard.
- [ ] Require `reason: "revert"` for backwards transitions; return 409 `illegal_transition` otherwise.
- [ ] Make same-stage requests idempotent (200, no notification, no broadcast).
- [ ] On entering `end`: delete all `live_locations` rows for the trip in the same transaction.
- [ ] Emit `stage.changed` on the trip room; emit `location.cleared` per purged user.
- [ ] Enqueue stage-change notifications for all trip members (integrates with `notifications`).

**Verify:** `pytest server/tests/test_stage_machine.py -q` covering: planning→holiday ok,
planning→end rejected, holiday→end purges live locations, revert without reason rejected,
member/family-admin get 403, idempotent repeat call. Then in `/docs`, PATCH a dev trip through
planning → holiday → end → revert and confirm the responses.

---

## Phase 3 — Check-ins: model, schema, router

- [ ] Add the `Checkin` SQLAlchemy model (`trip_id`, `user_id`, `lat`, `lng`, `accuracy_m`, `note`,
      timestamps) with an index on `(trip_id, created_at desc)`.
- [ ] Alembic migration for `checkins`; run it.
- [ ] Pydantic schemas: `CheckinCreate`, `CheckinRead` (embeds user + family colour, attachments,
      `low_accuracy` flag).
- [ ] `POST /api/v1/checkins` — `require_member`, `require_stage("holiday")`, lat/lng validation,
      per-user rate limit (1 per 10s → 429).
- [ ] `GET /api/v1/checkins` — cursor pagination, readable in all stages.
- [ ] `DELETE /api/v1/checkins/{id}` — owner, family admin (own family), or main admin;
      `require_stage("planning", "holiday")`.
- [ ] Broadcast `checkin.created` / `checkin.deleted` to the trip room.
- [ ] Allow `subject_type='checkin'` in the existing attachments upload route.

**Verify:** `pytest server/tests/test_checkins.py -q` — create/list/delete happy paths, 403 for
deleting someone else's, 409 in planning and end, 429 on rapid repeat. Manually POST a check-in via
`/docs` and confirm it appears in `GET /checkins`.

---

## Phase 4 — Live locations: model, schema, router, sweep

- [ ] Add the `LiveLocation` model with a unique constraint on `user_id`.
- [ ] Add `UserSettings` fields if not already present from `foundation`
      (`live_location_enabled` default false, `push_enabled` default false).
- [ ] Alembic migration; run it.
- [ ] `PUT /api/v1/live-locations/me` — upsert; 409 `sharing_disabled` when the user's setting is
      off; `require_stage("holiday")`.
- [ ] `DELETE /api/v1/live-locations/me` — idempotent 204, **no stage guard**.
- [ ] `GET /api/v1/live-locations` — excludes rows older than `LIVE_DROP_AFTER`, marks rows older
      than `LIVE_STALE_AFTER` as `stale`, excludes the caller's own row.
- [ ] Wire the settings toggle so setting `live_location_enabled=false` deletes the row in the same
      transaction and broadcasts `location.cleared`.
- [ ] Add a periodic background sweep deleting rows older than `LIVE_DROP_AFTER`, broadcasting
      `location.cleared` with `reason: "stale"`.
- [ ] Broadcast `location.updated` to the trip room excluding the sender.

**Verify:** `pytest server/tests/test_live_locations.py -q` — upsert keeps exactly one row per user;
toggle-off deletes the row; PUT with sharing disabled is 409; PUT in `end` is 409; DELETE in `end`
succeeds; stale rows are filtered from GET. Call the sweep task directly in a test with a frozen
clock.

---

## Phase 5 — Now/next and archive endpoints

- [ ] Implement the now/next resolver in `server/app/services/itinerary_clock.py`, timezone-aware,
      handling null `start_time`/`end_time` per `design.md`.
- [ ] `GET /api/v1/trips/{trip_id}/now-next` with an optional `?at=` override for tests.
- [ ] `GET /api/v1/trips/{trip_id}/archive` aggregating trip, itinerary, check-ins, photos, and
      `route_cache` rows — assert in code review that it makes **no** external API call.

**Verify:** `pytest server/tests/test_now_next.py -q` with table-driven cases: mid-item, gap between
items, last item of day, empty day, untimed items, day boundary in a non-UTC timezone. Then call
`/trips/{id}/now-next?at=...` in `/docs` for a seeded trip.

---

## Phase 6 — Web: stage plumbing

- [ ] Add the trip stage to the app-level store; subscribe to `stage.changed` in the ws client.
- [ ] Render the stage chip in the app shell (icon + label, semantic tokens, both themes).
- [ ] Route guard: redirect to a stage-appropriate default route when the stage changes underfoot.
- [ ] Add the shared `useStageGuard()` hook so feature UIs hide mutating controls in `end` — with a
      comment stating the server is the real enforcement.
- [ ] Map 409 `stage_forbidden` responses to inline messages in the shared API client, not toasts.
- [ ] Admin stage controls + confirm dialogs (advance, finish, and the quiet revert) in the admin
      screen, using the Sheet/Dialog primitive from `design-system`.

**Verify:** In two browser windows (admin + member), advance the stage as the admin and watch the
member's chip update live without a reload. Attempt a suggestion edit in `end` and confirm the
inline stage message appears.

---

## Phase 7 — Web: now / next screen

- [ ] Build `web/src/features/holiday-stage/NowNext.tsx` — two cards, type ramp per `design.md`,
      tabular figures for times.
- [ ] Skeleton loading state; designed empty states for "nothing now" and "nothing left today".
- [ ] Refresh on window focus, on a 60s timer, and on `stage.changed` / itinerary events.
- [ ] Make it the default mobile route while the stage is `holiday`; embed as a card atop the
      itinerary view on desktop.
- [ ] Tap-through from each card to the map focused on that item.

**Verify:** On a phone-sized viewport with a seeded itinerary, confirm the correct current/next items
render, the boundary rolls over when the clock passes an item's end time, and both empty states are
reachable.

---

## Phase 8 — Web: check-in flow

- [ ] Check-in button on the now/next screen and the map (≥44px target, thumb-reachable).
- [ ] Check-in sheet: locating state, resolved position, note field, preset chips ("Running late",
      "On our way", "We're here", "Stopping for food"), optional photo picker.
- [ ] `getCurrentPosition` wrapper with the documented options and per-error-code messaging
      (denied / unavailable / timeout / insecure context).
- [ ] Optimistic pin insertion with pending style and rollback on failure.
- [ ] Check-in feed list; select feed entry ↔ focus pin; detail in side panel (desktop) or bottom
      sheet (mobile).
- [ ] Delete own check-in with undo toast.
- [ ] Map layer for check-in pins: family colour, icon, initials, clustering, accuracy circle when
      `low_accuracy`.

**Verify:** With location permission granted, check in from a phone or device-emulated browser;
confirm the pin appears in a second logged-in browser within a second. Then deny permission and
confirm the specific error message, not a generic one.

---

## Phase 9 — Web: live location sharing

- [ ] Settings toggle with the privacy copy from `design.md`; default off; reads its true state from
      the server.
- [ ] `watchPosition` controller: throttle (15s / 25m), `visibilitychange` stop-and-restart with
      grace period, `pagehide` `sendBeacon` DELETE, Permissions API state check.
- [ ] Persistent "Sharing your location" indicator with a stop action and a polite live-region
      announcement.
- [ ] Live-marker map layer: distinct shape, pulsing ring honouring `prefers-reduced-motion`, name
      label, freshness caption, stale styling with explicit text.
- [ ] Layer toggles for live markers and check-ins.
- [ ] Stop the watch on `stage.changed` away from `holiday` and on 409 `sharing_disabled`.

**Verify:** On a real phone over HTTPS, enable sharing and confirm the marker appears and moves on a
second device; background the app and confirm the marker goes stale then disappears; toggle off and
confirm the marker vanishes immediately.

---

## Phase 10 — Web: End-stage archive

- [ ] Archive route: map + itinerary + check-in feed + photo grid + timeline, read-only.
- [ ] Banner explaining the trip is finished.
- [ ] Audit every feature surface so mutating controls are **absent** (not disabled) in `end`.
- [ ] Make the archive the default route when the stage is `end`.

**Verify:** Move a seeded trip to `end` and click through every route as a member — no create, edit,
or delete control should be reachable anywhere, and the archive should render the full trip.

---

## Phase 11 — Tests, accessibility, and docs

- [ ] Vitest: now/next resolver edge cases, check-in sheet states, stale-marker rendering, the
      sharing indicator's presence tied to watch state.
- [ ] Playwright: admin advances to holiday → member checks in → pin visible to admin → admin
      advances to end → member's create controls are gone.
- [ ] Keyboard pass: every stage control, the check-in sheet, and the feed are reachable with visible
      focus.
- [ ] Contrast check on stage chips, pins, and stale styling in both themes.
- [ ] Update this feature's docs if any behaviour changed during implementation (docs-first rule in
      `CLAUDE.md`).

**Verify:** `pytest` green in `server/`, `npm test` green in `web/`, Playwright holiday spec green
against the compose stack, and a manual reduced-motion check with the OS setting enabled.
