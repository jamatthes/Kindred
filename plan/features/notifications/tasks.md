# notifications — Tasks

**Read first:** this feature's `requirements.md` and `design.md`, plus `plan/architecture.md` and
`plan/design-system.md`. Milestone **M6**.

Assumes `foundation` (auth, sessions, websocket shell), `polls`, `map-suggestions`,
`voting-comments`, `itinerary-timeline`, and `holiday-stage` are implemented — this feature hooks
into their write paths.

---

## Phase 1 — Migration and models

- [ ] Add the `Notification` SQLAlchemy model for the existing `notifications` table
      (`recipient_user_id`, `type`, `payload_json` as JSONB, `read_at`).
- [ ] Add index `(recipient_user_id, created_at DESC)`.
- [ ] Add partial index on `(recipient_user_id) WHERE read_at IS NULL`.
- [ ] Add the **PROPOSED ADDITION** `NotificationPreference` model
      (`user_id`, `category`, `enabled`, unique on `(user_id, category)`).
- [ ] Alembic migration creating `notification_preferences` and both indexes; run it.
- [ ] Update `plan/architecture.md`'s schema section to include `notification_preferences`
      (docs-first rule), or remove the model if the addition is rejected at review.

**Verify:** `alembic upgrade head` then `alembic downgrade -1` and `upgrade head` again cleanly.
`pytest server/tests/test_models_notifications.py -q` asserting the unique constraint and that a
missing preference row reads as enabled.

---

## Phase 2 — Type registry and copy

- [ ] Create `server/app/services/notification_types.py` with the type registry from `design.md`:
      for each `type`, its category, `push_worthy` flag, subject type, and deep-link builder.
- [ ] Add server-side title/body renderers per type, taking `payload_json` and returning strings.
- [ ] Add a truncation helper applied to `summary` fields at generation time.
- [ ] Add a test that every registry entry has a renderer, a category, and a link builder — so
      adding a type without its copy fails the suite.

**Verify:** `pytest server/tests/test_notification_types.py -q` — registry completeness test plus a
snapshot of rendered title/body for each type against a sample payload.

---

## Phase 3 — Schemas and the notification service

- [ ] Pydantic schemas: `NotificationRead`, `NotificationListResponse` (items + `next_cursor` +
      `unread_count`), `PreferencesRead`, `PreferencesUpdate`, `NudgeResponse`.
- [ ] `server/app/services/notifications.py` with `create(...)` and `notify_trip(...)`.
- [ ] Recipient expansion helpers: trip members, comment-thread participants, mentioned users,
      non-voters for a subject.
- [ ] Actor exclusion — never notify the user who caused the event.
- [ ] Preference filtering by payload category.
- [ ] Collapsing logic: vote summary (6h), itinerary changes (15m) — merge into an **unread** row
      only, updating `payload_json` and `created_at`.
- [ ] Post-commit websocket dispatch hook so a rolled-back transaction broadcasts nothing.

**Verify:** `pytest server/tests/test_notification_service.py -q` — actor exclusion, per-recipient
row creation, preference filtering, collapse-into-unread, no-collapse-into-read, and a test that a
rolled-back transaction leaves zero rows and zero broadcasts.

---

## Phase 4 — Router

- [ ] `GET /api/v1/notifications` with cursor pagination and an `unread`/`all` filter.
- [ ] `GET /api/v1/notifications/unread-count`.
- [ ] `POST /api/v1/notifications/{id}/read` — returns 404 for another user's row.
- [ ] `POST /api/v1/notifications/read-all` with the optional `before` bound.
- [ ] `GET` / `PUT /api/v1/notification-preferences`.
- [ ] `POST /api/v1/polls/{id}/nudge` and `POST /api/v1/suggestions/{id}/nudge` —
      `require_main_admin`, `require_stage("planning","holiday")`, 24h per-subject-per-user limit,
      response reports `notified` and `skipped`.
- [ ] Confirm no endpoint accepts a `user_id` parameter.
- [ ] Ensure mark-read endpoints carry **no** stage guard.

**Verify:** `pytest server/tests/test_notifications_router.py -q` — pagination stability while new
rows arrive, 404 on foreign row, `read-all` with `before`, preferences round-trip, nudge permission
and rate limit. Then in `/docs`, list notifications for a seeded user, mark one read, and confirm
`unread_count` decrements in the same response.

---

## Phase 5 — Wire up the producers

- [ ] `suggestion.created` in the suggestions router.
- [ ] `suggestion.vote_summary` in the votes router (collapsing path).
- [ ] `suggestion.approved` / `suggestion.rejected` in the admin confirm/reject path.
- [ ] `comment.mention` and `comment.reply` in the comments router, parsing @mention markup.
- [ ] `poll.opened` / `poll.closed` in the polls router.
- [ ] `itinerary.changed` on itinerary add/move/remove (collapsing path).
- [ ] `stage.changed` in the stage endpoint from `holiday-stage`, including reverts.
- [ ] Audit: no router inserts `notifications` rows directly — all go through the service.

**Verify:** `pytest server/tests/test_notification_producers.py -q` — one test per trigger asserting
recipients, exclusion of the actor, and the resulting `type`/`category`/`push_worthy` values. Manual
check via `/docs`: approve a suggestion as admin, then list notifications as a member and see it.

---

## Phase 6 — WebSocket delivery

- [ ] Add per-user rooms to `server/app/ws.py` alongside the existing trip rooms.
- [ ] Emit `notification.new`, `notification.read`, `notification.updated` to **all** sessions of the
      recipient, including the acting session.
- [ ] Include the recomputed `unread_count` in every one of those payloads.
- [ ] Implement the resume handshake: client sends last-seen notification id; server replies with
      newer rows plus the authoritative count, or a `refetch` instruction when the gap exceeds 100.

**Verify:** `pytest server/tests/test_ws_notifications.py -q` with two simulated sessions for one
user: an event reaches both; marking read in one emits `notification.read` to both. Then open two
browser tabs logged in as the same user, mark a notification read in one, and watch the other's badge
update within a second.

---

## Phase 7 — Web: store, bell, badge

- [ ] Notification store in `web/src/features/notifications/` holding items, cursor, and
      `unread_count`, always trusting the server's count over local arithmetic.
- [ ] Seed the initial count from the page bootstrap payload so the badge is correct pre-socket.
- [ ] Subscribe to the three websocket events; apply idempotently.
- [ ] Polling fallback: `/unread-count` every 60s while the socket is disconnected; stop on reconnect.
- [ ] Bell button in the app shell with the badge (number + "9+" cap, accessible name including the
      count, AA-contrast tokens in both themes).

**Verify:** `npm test` for store reducers (new/read/updated idempotency). Manually kill the websocket
in devtools and confirm the badge falls back to polling and recovers on reconnect.

---

## Phase 8 — Web: dropdown and list page

- [ ] Dropdown popover on desktop, bottom sheet on mobile, using the Sheet/SidePanel primitive from
      `design-system`.
- [ ] Row component: icon, title, body, relative timestamp (tabular figures), unread dot, hover/touch
      "mark read" control, full-row click target.
- [ ] Unread styling using three signals (surface + dot + weight), never colour alone.
- [ ] Skeleton rows on first open; "Load older" with cursor paging; designed empty state.
- [ ] "Mark all as read" in the header, sending the `before` timestamp, disabled at zero.
- [ ] Keyboard support: Escape closes and restores focus to the bell; arrow keys traverse rows; Enter
      activates.
- [ ] `/notifications` full page with All/Unread filter and infinite scroll.

**Verify:** Keyboard-only pass — open the bell, arrow to the third row, Enter to navigate, confirm
focus lands sensibly. Confirm the empty state and the skeleton both render (throttle the network to
see the skeleton).

---

## Phase 9 — Web: deep links and preferences

- [ ] Deep-link router: suggestion/poll → open side panel or bottom sheet over the map; comment →
      navigate to parent, scroll into view, highlight with outline + tint; itinerary → select item and
      scrub the timeline; stage → trip screen.
- [ ] Cold-load support so a pasted deep link works from a fresh page load.
- [ ] "No longer available" inline state for missing subjects; still mark read.
- [ ] Optimistic mark-read on click with rollback and an inline error on failure.
- [ ] Preferences screen: six switches with explanations, immediate save, toast confirmation, and the
      mentions-off warning caption.

**Verify:** Paste a comment deep link into a fresh browser tab and confirm it lands on the right
comment with the highlight. Delete a suggestion, then click its notification, and confirm the
"no longer available" state rather than an error page.

---

## Phase 10 — Retention, tests, accessibility

- [ ] Scheduled cleanup task: delete read notifications older than 90 days, unread older than 180.
- [ ] Vitest: row rendering per type, unread styling, badge cap, deep-link resolution, "no longer
      available" state.
- [ ] Playwright: member A @mentions member B → B's badge increments live → B clicks through to the
      comment → badge clears.
- [ ] Contrast check on the badge, unread surface, and dot in both light and dark.
- [ ] Screen-reader pass: bell announces the unread count; the panel is announced as a list; the
      arrival of a notification does not steal focus.
- [ ] Update these docs if behaviour changed during implementation.

**Verify:** `pytest` green in `server/`, `npm test` green in `web/`, Playwright mention spec green
against the compose stack, and the retention task verified in a test with a frozen clock.
