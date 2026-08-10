# pwa-push — Requirements

**Read first:** `plan/overview.md`, `plan/architecture.md`, `plan/design-system.md`, `CLAUDE.md`,
and `plan/features/notifications/`. Milestone **M6**.

## Summary

Three related capabilities that turn Kindred from a website into something that behaves like an app
on a phone during a trip:

1. **Installable PWA** — web app manifest, icons, standalone display, so Kindred sits on the home
   screen next to the family's other apps.
2. **Offline read-only cache** — a service worker precaches the app shell and keeps the current
   itinerary and key info (addresses, notes) readable in dead zones. Rural Cornwall has no signal and
   that is exactly when you need to know where you are staying.
3. **Web Push** — self-hosted VAPID push for *high-value* notifications only, so the phone buzzes
   when an admin makes a decision, not when someone casts a vote.

**iOS is treated as a first-class flow, not a footnote.** On iPhone, push requires iOS 16.4 or later
**and** the app to have been added to the home screen. The app detects this and walks the user
through it instead of silently doing nothing.

Everything here requires a secure context (HTTPS). Per `plan/architecture.md` this is already
satisfied by Cloudflare in front of the origin.

## User stories

### Install

**P-1 — As a member on Android or desktop, I can install Kindred to my home screen.**
- A valid web app manifest is served with name "Kindred", short name, description, theme and
  background colours, `display: "standalone"`, `start_url`, and maskable icons at the required sizes.
- The browser's native install prompt is captured and offered at a sensible moment (an "Install
  Kindred" item in settings and a dismissible banner during Holiday), never as an interstitial on
  first load.
- Once installed, launching from the home screen opens in standalone mode with no browser chrome.
- Dismissing the install banner does not show it again for at least 30 days.

**P-2 — As a member on an iPhone, I get clear instructions for installing.**
- The app detects iOS Safari running outside standalone mode.
- It shows a friendly, illustrated walkthrough: tap the Share button → scroll → "Add to Home Screen"
  → Add — with the actual iOS icons pictured.
- The walkthrough explains *why* it matters ("this is the only way iPhones can send you alerts"),
  not just the steps.
- It can be dismissed and re-opened from settings at any time.
- If the browser is iOS but not Safari (e.g. Chrome on iOS), the walkthrough says the user needs to
  open Kindred in Safari to install it.

**P-3 — As an installed user, I see updates without reinstalling.**
- When a new version is deployed, the service worker fetches it in the background.
- The user gets an unobtrusive "A new version is ready — Reload" prompt rather than being reloaded
  underneath their fingers.
- If the user ignores it, the update applies on the next cold start.

### Offline

**P-4 — As a member with no signal, I can still see today's plan.**
- The current trip's itinerary (today and the surrounding days), including titles, times, addresses,
  place names, and notes, is readable with no network.
- Key info — accommodation addresses, contact notes, and any itinerary item notes — is included.
- The app shell (layout, navigation, fonts, icons) loads offline; the app never shows the browser's
  offline error page.
- A clear banner states "Offline — showing your saved copy, last updated <time>".
- Data older than a threshold is labelled as potentially stale rather than presented as current.

**P-5 — As a member offline, I am not misled about what I can do.**
- Actions that require the network (voting, commenting, checking in, creating suggestions) are
  visibly unavailable while offline, with an explanation — not buttons that fail on tap.
- No action is silently queued or lost. If I try, I am told to try again when I have signal.
- When the connection returns, the banner clears and the app refetches automatically.

**P-6 — As a member, the map degrades honestly offline.**
- Map tiles are not cached (licensing and size), so the map area shows a placeholder with the
  itinerary's addresses in text form rather than a broken grey void.
- Coordinates and addresses remain available so I can hand them to a native maps app.

### Push

**P-7 — As a member, I can turn on push notifications for this device.**
- A toggle in settings requests notification permission and subscribes the device.
- The toggle reflects the true state of *this* device — a device without a subscription reads as off
  even if another of my devices has push on.
- Turning it off unsubscribes this device and stops its pushes immediately.
- If I previously blocked notifications in the browser, the UI says so and explains how to unblock,
  rather than silently failing.

**P-8 — As a member, I get pushed only about things worth interrupting me for.**
Push is sent for: **admin approved a suggestion**, **admin rejected a suggestion**, **itinerary
changed**, **stage changed**, and **@mentions**.
Push is *not* sent for: individual votes, vote summaries, new suggestions, poll opened, replies I am
not mentioned in, or nudges.
- Tapping a push opens Kindred directly at the relevant screen.
- A push and its in-app notification are the same event — reading it in the app dismisses the need
  for the push, and the badge count stays consistent.

**P-9 — As a member, push respects the notification preferences I already set.**
- If I disabled a category in `notification-preferences`, I get neither the in-app notification nor a
  push for it.
- Push is an additional delivery channel for notifications that already exist; it never invents its
  own events.

**P-10 — As an admin, I can send myself a test push.**
- A "Send test notification" button in settings pushes a harmless test message to my own devices only.
- It reports success or the specific failure (no subscription, permission denied, endpoint expired).

**P-11 — As a member, my old devices stop getting pushes.**
- If a push endpoint is rejected as gone or expired by the push service, the subscription is deleted
  automatically so it is never retried.
- Logging out removes that device's subscription.

## Permissions

| Capability | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| Install the PWA | ✅ | ✅ | ✅ | ✅ (shell installs; content requires login) |
| See install walkthrough | ✅ | ✅ | ✅ | ✅ |
| Offline cached itinerary | ✅ | ✅ | ✅ | ❌ (nothing cached before login) |
| Subscribe/unsubscribe own device to push | ✅ | ✅ | ✅ | ❌ |
| See own push subscriptions | ✅ | ✅ | ✅ | ❌ |
| Send test push to self | ✅ | ✅ | ✅ | ❌ |
| Send push to another user | ❌ | ❌ | ❌ | ❌ |
| Broadcast an arbitrary push to everyone | ❌ | ❌ | ❌ | ❌ |
| Read another user's subscriptions | ❌ | ❌ | ❌ | ❌ |

There is deliberately **no** "message everyone" button for admins. Push is generated only by the
notification events listed in P-8, which keeps it impossible to use Kindred as a megaphone.

## Stage availability

| Capability | Planning | Holiday | End |
|---|---|---|---|
| Install / walkthrough | ✅ | ✅ (banner promoted) | ✅ |
| Offline itinerary cache | ✅ (itinerary may be sparse) | ✅ primary use case | ✅ (archive readable offline) |
| Push subscribe/unsubscribe | ✅ | ✅ | ✅ |
| Push delivery | ✅ (decisions, itinerary) | ✅ | Only the stage-change push announcing `end` |
| Test push | ✅ | ✅ | ✅ |

Subscription management is **not** stage-guarded — a frozen trip must not stop someone unsubscribing
their phone.

## Out of scope (v1)

- **Offline mutations / background sync / queued writes of any kind.** Offline is strictly read-only,
  per `plan/architecture.md`. A vote taken offline is not stored and not replayed.
- Caching map tiles or Google Places data (licensing, ToS, and size).
- Photo upload while offline.
- Push for every notification type — only the high-value set in P-8.
- Rich push features: images, action buttons, reply-from-notification.
- Native app wrappers (Capacitor, TWA, App Store / Play Store distribution).
- Any third-party push service (Firebase, OneSignal, Pusher). Kindred self-hosts VAPID.
- Email as a fallback channel — out of scope for v1 across the whole product.
- Push for logged-out or unauthenticated devices.
- Per-device naming/management UI beyond a simple list and revoke.
- Badging API / app-icon badge counts.
