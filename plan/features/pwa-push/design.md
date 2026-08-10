# pwa-push — Design

**Read first:** `plan/overview.md`, `plan/architecture.md`, `plan/design-system.md`, `CLAUDE.md`,
this feature's `requirements.md`, and `plan/features/notifications/design.md` (this feature consumes
its rows and its `push_worthy` flag).

## Data model

### Existing table (from `plan/architecture.md`)

**`push_subscriptions`** — `id`, `created_at`, plus:

| Column | Use |
|---|---|
| `user_id` | Owner. |
| `endpoint` | The push service URL returned by `PushManager.subscribe`. Unique. |
| `p256dh` | Client public key for payload encryption. |
| `auth` | Client auth secret. |
| `user_agent` | Captured at subscribe time so the settings list can say "iPhone — Safari". |

Additions to the existing table, needed for lifecycle handling (P-11):

**PROPOSED ADDITION** — two columns on `push_subscriptions`:

```
last_used_at      timestamptz null   -- last successful send
failure_count     int not null default 0
```

Rationale: without these, a dead endpoint is retried forever and there is no way to prune devices a
family member stopped using. Both are additive and nullable/defaulted, so the migration is trivial.
A unique index on `endpoint` is also required — the same browser re-subscribing must update rather
than duplicate.

NOTE: `plan/architecture.md` lists `push_subscriptions` without these columns. If the addition is
accepted, update that schema section in the same commit as the migration, per `CLAUDE.md`.

### `push_enabled` vs `push_subscriptions` — the ownership rule

`user_settings.push_enabled` and the `push_subscriptions` rows answer different questions, and
conflating them is the classic bug in this feature:

- **`user_settings.push_enabled` is intent.** "This user wants push in principle." It is a single
  per-user flag and it gates whether the server bothers to look for subscriptions at all.
- **`push_subscriptions` rows are device truth.** "This specific browser on this specific device has
  a live push endpoint." Only a row can actually receive a push.

Rules that follow:

1. The settings toggle on a device performs **both**: it sets `push_enabled = true` and creates the
   row for that device. Turning it off deletes **only that device's row**, and sets
   `push_enabled = false` only when it was that user's last remaining subscription.
2. The UI toggle's displayed state is derived from **the current device's subscription**, not from
   `push_enabled`. Otherwise a user with push on their phone would see "on" on their laptop and
   wonder why nothing arrives.
3. Sending checks `push_enabled` first (a cheap short-circuit), then iterates the user's rows.
4. `push_enabled` never causes a push on its own, and a stray row never causes a push if
   `push_enabled` is false. Both must agree.
5. Logging out deletes the current device's row. It does **not** change `push_enabled`.

### Relationship to notifications

This feature creates **no events of its own**. It reads `notifications` rows created by
`plan/features/notifications/` and sends a push when `payload_json.push_worthy` is true. The
push-worthy set is defined in the notifications type registry — a single source of truth, so the two
channels can never disagree about what is important.

Category preferences are already applied when the notification row is created, so push inherits them
for free (P-9) with no second check.

## VAPID keys

- A single application-server keypair, generated once at deploy time with a documented one-line
  command, stored in `deploy/.env` as `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and
  `VAPID_SUBJECT` (a `mailto:` for the operator). `deploy/.env.example` already reserves VAPID keys.
- No external push provider is involved. The browser's own push service (FCM endpoint for Chrome,
  Mozilla's for Firefox, Apple's for Safari) is contacted directly by our server; VAPID is how we
  identify ourselves to it. Nothing about this requires a Firebase account.
- **Rotating the keypair invalidates every existing subscription.** This is documented in the deploy
  README as a one-way operation requiring all users to re-subscribe. The public key is served from an
  endpoint rather than baked into the JS bundle so a rotation does not require a rebuild.

## REST endpoints

All under `/api/v1/`, session cookie auth, CSRF on mutations.

| Method | Path | Request | Response | Dependencies |
|---|---|---|---|---|
| `GET` | `/push/vapid-public-key` | — | `{ key: "BASE64URL" }` | `require_member` |
| `POST` | `/push/subscriptions` | `{ endpoint, keys: { p256dh, auth } }` | `201 { id, endpoint, user_agent, created_at }` | `require_member` — **no stage guard** |
| `DELETE` | `/push/subscriptions` | `{ endpoint }` | `204` | `require_member` — **no stage guard** |
| `GET` | `/push/subscriptions` | — | `{ items: [{ id, user_agent, created_at, last_used_at, is_current }] }` | `require_member`, own rows only |
| `DELETE` | `/push/subscriptions/{id}` | — | `204` | `require_member` + ownership |
| `POST` | `/push/test` | — | `{ sent, failed, detail? }` | `require_member` — sends only to the caller's own devices |

Notes:
- `POST /push/subscriptions` is an **upsert on `endpoint`**. Browsers hand back the same endpoint on
  repeat subscribe, and re-subscribing must not create duplicates.
- It also sets `user_settings.push_enabled = true` in the same transaction.
- `DELETE /push/subscriptions` deletes by endpoint (the client always knows its own endpoint) and
  sets `push_enabled = false` only if no rows remain for that user.
- `GET /push/subscriptions` never returns `endpoint`, `p256dh`, or `auth` — those are secrets that
  serve no UI purpose. `is_current` is computed by the client comparing its own endpoint hash.
- `/push/subscriptions/{id}` for another user returns **404**, not 403.
- None of these carry a stage guard: unsubscribing must work in `end`.

## Sending

Lives in `server/app/services/push.py`, behind an interface so tests fake it — required by the
testing strategy in `plan/architecture.md` ("never hit external services from the test suite").

```
class PushSender(Protocol):
    def send(self, subscription, payload: dict) -> PushResult: ...
```

Flow, triggered after a notification row is committed:

1. Skip unless `payload_json.push_worthy` is true.
2. Skip unless the recipient's `user_settings.push_enabled` is true.
3. **Skip if the recipient has an active websocket session** — they are looking at the app right now
   and the in-app notification already told them. This avoids the double-buzz that makes people turn
   push off. (Applied with a short grace window rather than instantaneously.)
4. Load the recipient's subscriptions and send to each, as a background task — never inline in the
   request that caused it.

Push payload (kept small; push services cap payload size around 4KB):
```json
{ "title": "Sam approved Tintagel Castle",
  "body": "It's now on the itinerary for Tue 14 Jul",
  "tag": "notification-<id>",
  "url": "/suggestions/<id>",
  "notification_id": "<uuid>" }
```
`title`/`body` reuse the server-side renderers from `notifications` — one copy source for both
channels. `tag` lets the OS replace a superseded notification rather than stacking duplicates.

### Failure handling (P-11)

| Push service response | Action |
|---|---|
| 201 / 200 | Set `last_used_at`, reset `failure_count` to 0 |
| **404 or 410 Gone** | Delete the subscription row immediately — the endpoint is permanently dead |
| 400 / 401 / 403 | Log loudly; almost always a VAPID misconfiguration, not a user problem. Do not delete rows |
| 413 Payload too large | Log; truncate body and retry once |
| 429 / 5xx | Increment `failure_count`, retry with backoff; delete after 10 consecutive failures |

Deleting on 410 is the important one — it is how the table stays clean without any user action.

## Service worker

Location: `web/public/sw.js` (or generated by the Vite PWA plugin), registered from the app shell
after first paint so registration never blocks initial render.

### Caching strategy

| Asset class | Strategy | Cache name |
|---|---|---|
| App shell — HTML entry, JS/CSS bundles, fonts, icons | **Precache** at install, revision-hashed | `kindred-shell-v<build>` |
| `GET /api/v1/trips/{id}` | Stale-while-revalidate | `kindred-data` |
| `GET /api/v1/itinerary?trip_id=` | Stale-while-revalidate | `kindred-data` |
| `GET /api/v1/trips/{id}/now-next` | Network-first, short cache fallback | `kindred-data` |
| `GET /api/v1/families` (home addresses) | Stale-while-revalidate | `kindred-data` |
| Uploaded attachment thumbnails | Cache-first, capped by count | `kindred-media` |
| **Google Maps tiles, Places, any Google endpoint** | **Never cached** — ToS and the cost rule in `CLAUDE.md` | — |
| All other `/api/**` | Network-only | — |
| Any mutation (POST/PUT/PATCH/DELETE) | **Network-only, never queued** — offline mutations are out of scope | — |

Every cached API response is stored with a timestamp so the UI can render "last updated <time>"
honestly (P-4).

### Lifecycle

- `install` → precache the shell, then `skipWaiting()` is **not** called automatically.
- `activate` → delete caches whose names do not match the current build.
- A new worker waiting triggers a message to the page, which shows the "new version ready" prompt
  (P-3). Only when the user accepts does the page post `SKIP_WAITING` and reload.
- On logout, the page posts a `CLEAR_CACHES` message and the worker purges `kindred-data` and
  `kindred-media` — cached trip data must not survive a logout on a shared device.

### Push event handlers

- `push` → parse the payload, call `showNotification(title, { body, tag, data: { url }, icon, badge })`.
  If the payload fails to parse, show a generic "New activity in Kindred" rather than nothing.
- `notificationclick` → close the notification, then focus an existing Kindred window and navigate it
  to `data.url`, or open a new window at that URL if none is open. This is what makes P-8's
  "tapping opens the right screen" work, including from a cold start.
- `pushsubscriptionchange` → re-subscribe with the stored VAPID key and POST the new subscription,
  so browser-initiated rotations do not silently kill push.

## Manifest

`web/public/manifest.webmanifest`:

| Field | Value |
|---|---|
| `name` | "Kindred" |
| `short_name` | "Kindred" |
| `description` | Short product line |
| `start_url` | `/?source=pwa` |
| `scope` | `/` |
| `display` | `standalone` |
| `orientation` | `portrait-primary` (mobile is the install target) |
| `theme_color` / `background_color` | **Read from the design tokens at build time** — never hand-typed hex, per the token-only rule in `CLAUDE.md` |
| `icons` | 192, 512, and a 512 `maskable` variant; plus Apple touch icon links in the HTML head |
| `categories` | `["travel", "productivity"]` |

NOTE: a manifest is a static JSON file and cannot reference CSS custom properties, so the two colour
values are injected from the token source during the build. This is the one sanctioned place a
literal colour value is emitted, and it is generated, not authored.

### Share target (suggest-by-share)

The manifest also registers Kindred as a **share target**, so a phone's native share sheet
(e.g. from the Airbnb or Google Maps app) can send a URL straight into the
"Suggest a place" flow:

```json
"share_target": {
  "action": "/suggest/shared",
  "method": "GET",
  "params": { "title": "title", "text": "text", "url": "url" }
}
```

`/suggest/shared` requires login, extracts the first URL from `url`/`text` (some apps put
it in `text`), and opens the create-suggestion flow with that URL pasted — from there the
`map-suggestions` link-preview endpoint takes over (OG prefill, Airbnb-aware extras).
Available once installed: broadly on Android; on iOS from the home-screen app. During
Planning and Holiday stages only — in End stage the route shows the frozen-trip notice.

## iOS flow (first-class, per P-2)

The constraints, stated plainly so implementers do not fight them:

- Web Push on iOS requires **iOS 16.4+**.
- It requires the app to have been **added to the home screen**; Safari tabs cannot receive push.
- `Notification.requestPermission()` must be called from a **user gesture** inside the installed app.
- There is no `beforeinstallprompt` event on iOS — installation is manual, via Share → Add to Home
  Screen. There is no way to trigger it programmatically, and no amount of effort will change that.
- Non-Safari browsers on iOS use WebKit but cannot install to the home screen for this purpose.

Detection logic:

```
isIOS          = /iP(hone|ad|od)/ test on UA, or iPadOS masquerading as Mac with touch support
isStandalone   = window.navigator.standalone === true || matchMedia('(display-mode: standalone)').matches
isIOSSafari    = isIOS && not Chrome/Firefox/Edge iOS UA tokens
supportsPush   = 'PushManager' in window && 'serviceWorker' in navigator
```

Resulting states and what the UI does:

| State | UI |
|---|---|
| iOS Safari, not installed | Push toggle is shown disabled with "Add Kindred to your home screen first", opening the illustrated walkthrough |
| iOS, installed, `supportsPush` | Normal push toggle |
| iOS, installed, no `PushManager` (pre-16.4) | "Your iPhone needs iOS 16.4 or later for alerts. Kindred still works — you'll see updates in the app." |
| iOS, non-Safari browser | "Open Kindred in Safari to add it to your home screen" |
| Android/desktop with `beforeinstallprompt` captured | "Install Kindred" button triggering the native prompt |
| Already installed anywhere | Install UI hidden entirely |

The walkthrough is a bottom sheet with three numbered steps, each showing the real iOS Share and
"Add to Home Screen" glyphs, and a closing line explaining the payoff. It is reachable from settings
forever, not just on first run — people dismiss things and change their minds.

## UI behaviour

Per `plan/design-system.md`. Tokens only, both themes, ≥44px targets.

- **Install banner** — a dismissible bar, shown at most once per 30 days, promoted during Holiday
  when it is most useful. Never an interstitial or a modal on first load.
- **Settings → Notifications section** — the push toggle, the device list, the test button, and the
  install/walkthrough entry point, grouped together with the in-app preferences from `notifications`
  so a user finds all alerting controls in one place.
- **Device list** — one row per subscription: friendly label parsed from `user_agent`
  ("iPhone — Safari"), "added <date>", "last used <date>", a "This device" marker, and a revoke
  control. Revoking another device shows an undo toast.
- **Permission-blocked state** — when `Notification.permission === 'denied'`, the toggle is disabled
  with browser-specific guidance on unblocking, because a re-request will not prompt again.
- **Offline banner** — a persistent, non-dismissible bar at the top of the content area:
  "Offline — showing your saved copy from 14:32". Uses `--color-warning` surface with an icon, not
  colour alone. Clears automatically on reconnect and triggers a refetch.
- **Offline disabling of actions** — mutating controls are disabled with a shared tooltip/caption
  ("Needs a connection"), consistently, via one `useOnline()` hook rather than ad-hoc checks.
- **Offline map** — the map region renders a placeholder card listing the itinerary's addresses as
  selectable text with a "copy address" action, so the user can paste into a native maps app. It does
  not render a grey void or a broken tile grid.
- **Update prompt** — a low-priority toast-like bar, "A new version of Kindred is ready", with
  "Reload" and a dismiss. It never reloads without consent.
- **Motion** — install sheet and banners follow the 150–250ms motion rules and respect
  `prefers-reduced-motion`.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| Non-secure context (dev over plain HTTP on a LAN IP) | Service worker and push are unavailable. The UI states the reason explicitly rather than showing a broken toggle. `localhost` is a secure context and works. |
| User grants notification permission but the subscribe call fails | Toggle reverts to off with a specific error; no half-state is persisted server-side. |
| Same browser subscribes twice | Upsert on `endpoint` — one row. |
| User clears browser data | Subscription is gone client-side; the server row lingers until its next send returns 410 and is deleted. |
| Two family members share a device/browser profile | Logout purges the data caches and deletes that device's subscription, so the next user does not inherit either. |
| Push arrives while the app is open and focused | Suppressed (rule 3 in Sending). The in-app notification still appears. |
| Push arrives for a notification already read on another device | The OS notification may already be shown; `tag` reuse means a later push replaces rather than stacks. Clicking a stale one still deep-links correctly and is harmless. |
| Payload exceeds the push service size cap | Body truncated server-side before sending; the full text lives in the app. |
| VAPID keys missing or malformed at boot | The API logs a clear startup error and disables push endpoints with a 503 rather than failing per-request in confusing ways. |
| VAPID keys rotated | All existing subscriptions become invalid and are pruned on their next 410. Documented as a deliberate, disruptive operation. |
| Offline with an empty cache (first ever visit was offline) | The shell cannot be cached yet; show the offline state with an explanation rather than a browser error page. |
| Cached itinerary is days old | Banner states the cache age; entries older than the threshold carry a "may be out of date" caption. |
| Trip enters `end` while a device is offline | The cached copy is still readable; on reconnect the app syncs and switches to the archive view. |
| User taps a push for a deleted subject | Deep-links normally and shows the "no longer available" state from `notifications`. |
| Service worker update fails to install | The old worker keeps serving; failure is logged, and the user sees no error — the app still works. |
| Storage quota exceeded | `kindred-media` is capped by entry count and trimmed oldest-first; the shell and data caches take priority. |
