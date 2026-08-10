# pwa-push — Tasks

**Read first:** this feature's `requirements.md` and `design.md`, plus `plan/architecture.md`,
`plan/design-system.md`, and `plan/features/notifications/`. Milestone **M6**.

Depends on `notifications` being complete — this feature consumes its rows, its `push_worthy` flag,
and its server-side title/body renderers.

---

## Phase 1 — Migration and models

- [ ] Add the `PushSubscription` SQLAlchemy model for the existing `push_subscriptions` table.
- [ ] Add the **PROPOSED ADDITION** columns `last_used_at` (nullable timestamptz) and
      `failure_count` (int, default 0).
- [ ] Add a unique index on `endpoint`.
- [ ] Alembic migration; run it.
- [ ] Update `plan/architecture.md`'s `push_subscriptions` entry to match, per the docs-first rule
      (or drop the columns if the addition is rejected at review).

**Verify:** `alembic upgrade head`, `downgrade -1`, `upgrade head` cleanly.
`pytest server/tests/test_models_push.py -q` asserting the endpoint uniqueness constraint.

---

## Phase 2 — VAPID configuration

- [ ] Add `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` to `server/app/core/config.py`.
- [ ] Add all three to `deploy/.env.example` with a comment showing the one-line generation command.
- [ ] Document key generation and the "rotation invalidates every subscription" warning in the deploy
      README.
- [ ] Fail startup loudly with a clear message if the keys are absent or malformed; disable the push
      router with 503 rather than erroring per request.

**Verify:** Start the API with the keys removed and confirm a single clear startup error and a 503
from `GET /api/v1/push/vapid-public-key`. Restore them and confirm the key endpoint returns the
public key.

---

## Phase 3 — Push service

- [ ] Create the `PushSender` protocol and a real implementation in `server/app/services/push.py`
      using a web-push library for VAPID signing and payload encryption.
- [ ] Create a `FakePushSender` for tests that records calls and can be told to return specific
      status codes.
- [ ] Implement the failure table from `design.md`: 410/404 → delete row; 4xx auth → log, keep row;
      413 → truncate and retry once; 429/5xx → backoff, delete after 10 consecutive failures.
- [ ] Update `last_used_at` and reset `failure_count` on success.
- [ ] Payload builder reusing the notification title/body renderers, with body truncation.

**Verify:** `pytest server/tests/test_push_service.py -q` with the fake sender covering every row of
the failure table, especially that a 410 deletes the subscription and a 500 does not.

---

## Phase 4 — Push router

- [ ] Pydantic schemas: `SubscriptionCreate`, `SubscriptionRead` (no secrets), `TestPushResponse`.
- [ ] `GET /api/v1/push/vapid-public-key`.
- [ ] `POST /api/v1/push/subscriptions` — upsert on endpoint, capture `user_agent`, set
      `user_settings.push_enabled = true` in the same transaction.
- [ ] `DELETE /api/v1/push/subscriptions` by endpoint — clear `push_enabled` only when it was the
      last row.
- [ ] `GET /api/v1/push/subscriptions` — own rows, never returning `endpoint`/`p256dh`/`auth`.
- [ ] `DELETE /api/v1/push/subscriptions/{id}` — ownership enforced, 404 for foreign rows.
- [ ] `POST /api/v1/push/test` — sends only to the caller's own devices.
- [ ] Confirm **no stage guard** on any of these routes.

**Verify:** `pytest server/tests/test_push_router.py -q` — double-subscribe creates one row;
unsubscribing the last device clears `push_enabled` but unsubscribing one of two does not; foreign
subscription returns 404; secrets absent from the list response; all routes work with the trip in
`end`. Then subscribe and list via `/docs`.

---

## Phase 5 — Dispatch from notifications

- [ ] Hook the push dispatcher into the notification service's post-commit path.
- [ ] Gate on `payload_json.push_worthy` **and** `user_settings.push_enabled`.
- [ ] Suppress push when the recipient has an active websocket session (with a short grace window).
- [ ] Send as a background task, never inline in the triggering request.
- [ ] Assert in tests that a non-push-worthy notification sends nothing.

**Verify:** `pytest server/tests/test_push_dispatch.py -q` — approving a suggestion pushes; casting a
vote does not; a recipient with an open socket is skipped; a recipient with `push_enabled=false` is
skipped; a category the user disabled produces neither a notification nor a push.

---

## Phase 6 — Manifest and icons

- [ ] Generate icons at 192, 512, and a 512 maskable variant, plus the Apple touch icon.
- [ ] Create `web/public/manifest.webmanifest` with the fields from `design.md`.
- [ ] Inject `theme_color` / `background_color` from the design tokens **at build time** — no
      hand-typed hex anywhere in the source.
- [ ] Link the manifest and Apple touch icons in the HTML head.

**Verify:** Chrome DevTools → Application → Manifest shows no warnings and the install icon appears
in the address bar. Run Lighthouse and confirm the Installable check passes.

---

## Phase 7 — Service worker: shell and offline data

- [ ] Register the service worker after first paint.
- [ ] Precache the app shell with build-revisioned names; delete stale caches on activate.
- [ ] Implement the routing table from `design.md`: stale-while-revalidate for trip, itinerary, and
      families; network-first for now-next; cache-first capped for media; network-only for everything
      else.
- [ ] **Explicitly bypass every Google endpoint** — tiles, Places, Maps JS — with a comment citing
      the ToS and the cost rule.
- [ ] **Never intercept or queue mutations.** Add a comment stating offline writes are out of scope.
- [ ] Store a timestamp with each cached API response for the "last updated" label.
- [ ] Handle `CLEAR_CACHES` on logout, purging data and media caches.

**Verify:** Load the app, go offline in DevTools, and reload — the shell and today's itinerary render
with the offline banner and a correct "last updated" time. Confirm the Network tab shows no Google
requests served from cache.

---

## Phase 8 — Service worker: update flow and push handlers

- [ ] Do not call `skipWaiting()` automatically; message the page when a new worker is waiting.
- [ ] Page-side "A new version is ready — Reload" prompt that posts `SKIP_WAITING` and reloads only
      on user action.
- [ ] `push` handler → `showNotification` with title, body, tag, icon, badge, and `data.url`;
      generic fallback if the payload will not parse.
- [ ] `notificationclick` → focus an existing window and navigate, or open a new one at `data.url`.
- [ ] `pushsubscriptionchange` → re-subscribe and POST the new subscription.

**Verify:** Deploy a changed build and confirm the update prompt appears rather than an automatic
reload. Send a test push from settings, tap it from a locked phone, and confirm it opens the correct
screen.

---

## Phase 9 — Web: install and platform detection

- [ ] `usePlatform()` hook exposing `isIOS`, `isIOSSafari`, `isStandalone`, `supportsPush`,
      `canPrompt`.
- [ ] Capture and store `beforeinstallprompt`; expose an install trigger.
- [ ] Install banner: dismissible, at most once per 30 days (persisted), promoted during Holiday,
      never an interstitial.
- [ ] iOS walkthrough bottom sheet: three numbered steps with the real Share and Add-to-Home-Screen
      glyphs, plus a "why this matters" line; re-openable from settings.
- [ ] Render each of the six platform states from the table in `design.md` with its exact message.

**Verify:** On a real iPhone in Safari, confirm the walkthrough appears with the correct copy; add to
home screen and confirm the push toggle becomes enabled. On Android Chrome, confirm the native
install prompt fires from the settings button.

---

## Phase 10 — Web: push settings and offline UI

- [ ] Push toggle deriving its state from **this device's** subscription, not `push_enabled`.
- [ ] Subscribe flow: fetch the VAPID key, request permission from a user gesture, `PushManager
      .subscribe`, POST the subscription; revert the toggle on any failure.
- [ ] Unsubscribe flow: `PushManager.unsubscribe` plus DELETE.
- [ ] Permission-denied state with browser-specific unblock guidance.
- [ ] Device list with parsed labels, dates, "This device" marker, and revoke with undo toast.
- [ ] "Send test notification" button reporting specific failures.
- [ ] `useOnline()` hook; offline banner with the cache timestamp; consistent disabling of every
      mutating control with a "Needs a connection" caption.
- [ ] Offline map placeholder listing itinerary addresses as copyable text.
- [ ] Group all of this with the in-app notification preferences in one settings section.

**Verify:** Toggle push on, receive a test push, revoke the device from the list, and confirm no
further pushes arrive. Go offline and confirm every vote/comment/check-in control is visibly
unavailable with an explanation and none of them silently fail.

---

## Phase 11 — Tests, audits, device matrix

- [ ] Vitest: platform detection across UA fixtures (iOS Safari, iOS Chrome, iPadOS-as-Mac, Android,
      desktop), toggle state derivation, offline banner, disabled-control behaviour.
- [ ] Playwright: install-prompt path on Chromium; offline reload serving the cached itinerary.
- [ ] Lighthouse PWA audit passing Installable and offline-capable checks.
- [ ] Real-device matrix, recorded in the deploy README: iPhone Safari installed (push works),
      iPhone Safari uninstalled (walkthrough shown), Android Chrome, desktop Chrome, desktop Firefox.
- [ ] Verify logout purges caches and the device subscription on a shared browser profile.
- [ ] Confirm the test suite never contacts a real push service.
- [ ] Update these docs if behaviour changed during implementation.

**Verify:** `pytest` green in `server/`, `npm test` green in `web/`, Lighthouse PWA checks passing,
and a signed-off manual pass on at least one real iPhone and one real Android device — emulators are
not sufficient evidence for the iOS push path.
