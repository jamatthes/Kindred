# holiday-stage — Requirements

**Read first:** `plan/overview.md`, `plan/architecture.md`, `plan/design-system.md`, `CLAUDE.md`.
Milestone **M5** (End-stage archive polish lands in M7).

## Summary

The stage machine and everything that only matters once the trip is real. A trip moves
`planning → holiday → end`. Advancing is owner-or-organiser-only and confirmed. During **Holiday** the
product pivots to the phone: a "now / next up" screen, a one-tap check-in that drops a
family-coloured pin on the shared map, an opt-in foreground live-location share, and a "running
late" quick status. Suggestions keep working during Holiday and are still admin-confirmed. **End**
freezes the whole trip read-only and turns it into a browsable archive/scrapbook.

**Privacy is a feature, not a limitation.** Live location only runs while the app is open in the
foreground. There is no background tracking on the web, and we do not pretend otherwise. The
toggle is off by default and there is a visible indicator the entire time sharing is active.

## User stories

### Stage machine

**HS-1 — As the owner or an organiser, I can move the trip from Planning to Holiday.**
- A "Start holiday" control is visible to the owner and to organisers only, on the trip/admin
  screen.
- Activating it opens a real confirm dialog (admin-destructive action, per `design-system.md`)
  naming the current and target stage and summarising the effect in one line.
- On confirm the trip's stage changes and every connected client updates without a reload.
- A notification is generated for all trip members (see `plan/features/notifications/`).
- Anyone who is neither owner nor organiser never sees the control, and the endpoint rejects
  them with 403.

**HS-2 — As the owner or an organiser, I can move the trip from Holiday to End.**
- Same confirm pattern, with explicit wording that End makes the trip read-only for everyone.
- After the change, every mutating endpoint in the application rejects writes for this trip.
- The UI switches to the archive view as its default surface.

**HS-3 — As the owner or an organiser, I can revert a stage change I made by mistake.**
- A separate, deliberately less prominent "Revert stage" control moves the trip back one stage.
- Requires typing/confirming a second time, and states that reverting un-freezes the trip.
- Reverting generates a notification to all members so it is never silent.
- Forward transitions are the normal path; reverting exists only as an escape hatch.
- NOTE: the source docs describe stages as a forward progression and do not mention reverting.
  This is an approved addition — without it, an accidental "End" would permanently freeze a trip.

**HS-4 — As any member, I can see the current stage at all times.**
- The app shell shows a stage indicator (Planning / Holiday / End) using semantic tokens.
- When the stage changes while I am looking at the app, the indicator updates live and a toast
  confirms it; the persistent record is the notification, not the toast.

### Holiday: now / next up

**HS-5 — As a member on my phone during Holiday, the app opens on "now / next up".**
- During Holiday, the default mobile route is the now/next screen.
- It shows the **current** itinerary item (the one whose time window contains now) and the
  **next** one, each with title, time, location name, and a tap target that opens the map.
- Type is large and glanceable — readable at arm's length, one-handed, in sunlight.
- If nothing is happening now, the "now" slot shows a friendly empty state and next-up is promoted.
- If nothing is left today, it shows tomorrow's first item labelled as such.
- If the itinerary is empty, an empty state points to the itinerary view.
- The screen refreshes on focus and when an `itinerary.*` or stage websocket event arrives.
- Each item with a location carries a prominent **"Open in Google Maps"** action (≥44px)
  that opens the native Maps app for turn-by-turn navigation to the location, via a
  universal Maps deep link (`https://www.google.com/maps/dir/?api=1&destination=…`) — a
  plain URL, no API key or quota involved. Items without a location omit the action.

### Holiday: check-in

**HS-6 — As a member, I can check in with one tap.**
- A prominent check-in button is available during Holiday on the now/next screen and the map.
- Tapping it takes a single `navigator.geolocation` fix (no continuous watching) and POSTs it.
- On success, a pin appears on the shared map in my family's colour and an entry appears in the
  check-in feed for everyone, live.
- I can optionally add a short note before or after sending.
- I can attach a photo to a check-in (stored as an attachment).
- Denied permission, timeout, or unavailable location each produce a specific, human error message
  and never a silent failure.

**HS-7 — As a member, I can say "running late" in one tap.**
- The check-in control offers preset notes, "Running late" being the first.
- Choosing a preset performs a normal check-in with that note attached — there is no separate
  status object to manage or clear.
- The resulting feed entry and pin are visually distinguishable by an icon plus the note text
  (never colour alone).

**HS-8 — As a member, I can browse the check-in feed and map.**
- The feed lists check-ins newest-first with who, when, note, and photo thumbnail.
- Selecting a feed entry focuses its pin; selecting a pin opens the entry in the side panel
  (desktop) or bottom sheet (mobile).
- I can delete my own check-in; admins can delete any. Deletion of my own is undoable via toast
  (undo over confirm, per `design-system.md`).

### Holiday: live location

**HS-9 — As a member, I can opt in to sharing my live location while the app is open.**
- The toggle lives in my settings and is **OFF by default** — unless my family's head (or
  spouse) set our family's default to on before I joined, in which case it starts on and I am
  asked once before anything is sent (see HS-15).
- The settings copy states plainly: sharing only works while the app is open and in the
  foreground; closing the app or switching away stops it; there is no background tracking.
- Turning it on requests geolocation permission and starts `watchPosition`.
- While active, a persistent, always-visible "Sharing location" indicator is shown in the app
  shell, with a one-tap stop.
- If my family's settings are currently hiding me, the indicator says so rather than claiming
  I am visible. An indicator that overstates what is being shared is worse than none.
- Position updates are throttled and only sent when the position meaningfully changed.
- **Nobody can turn this toggle on for me.** My family's head or spouse can prevent my
  location being shown and can choose what the toggle starts at for people who join after
  them, but the act of sharing is mine alone, and my browser's permission prompt is mine alone
  to answer.

**HS-10 — As a member, I can stop sharing at any time, and it really stops.**
- Toggling off stops the watch and deletes my `live_locations` row server-side.
- My marker disappears from everyone else's map immediately via websocket.
- Backgrounding the tab, closing it, or losing the session also stops sharing; the server treats
  rows that stop updating as stale and stops showing them as live.

**HS-11 — As a member, I can see who is currently sharing.**
- **Every sharing person gets their own marker.** There is no grouping into one pin per family
  and no "representative member" — if four people in a family are sharing, four markers appear.
  The product's question on the day is "where is each person", not "where is each household".
- A marker is that person's profile picture in a circle, ringed in their family's colour. With
  no picture, their initials on a neutral fill, ringed the same way.
- Hovering or focusing a marker shows their full name. On touch, a tap shows the same label
  before opening anything, so the name is reachable without a pointer.
- Family colour is never the only carrier: the name is always one interaction away, and the
  side panel lists everyone sharing with their family named in words.
- A freshness label — "last updated N min ago" — accompanies the marker.
- Markers older than the staleness threshold are shown as stale (muted + explicit label) and then
  dropped, rather than silently pretending to be current.
- When several people are in the same place, their markers cluster rather than stacking into an
  unreadable pile; opening the cluster lists them by name.
- Only members of the same trip can see them.
- I only see people whose family settings permit it (HS-15). I am never told that somebody is
  hidden by a setting versus simply not sharing — from outside their family, the two look the
  same, which is what stops the map becoming a way to audit other people's choices.

**HS-15 — As the head of my family (or a spouse), I decide which of my family appear on the
map.**
- I have one switch for the whole family and one per member, and I set what new members start
  with. All three live in my family's settings, not on the map.
- Turning the family switch off removes all of us, myself included, immediately and for
  everyone.
- **None of my switches can start someone sharing.** They can only stop it. Turning them all on
  puts nobody on the map who has not chosen to be there.
- My own sharing starts on when I create the family; everyone else starts from the default I
  set, and is asked before anything is sent.
- A spouse has every one of these powers — the family switch, everyone else's per-member
  switch, and the new-member default — with one asymmetry: a spouse cannot flip the head's own
  per-member visibility switch, matching `plan/overview.md`'s Roles section ("a spouse cannot
  ... change the head's switches"). The head can flip a spouse's. This is the same
  one-directional rule as the rest of the head/spouse relationship, applied to the one switch
  that is personally the head's.
- The full rules, and the reasoning behind them, live in `plan/features/families/`
  (FM-15) — that feature owns these settings; this one only reads them.

> NOTE: an earlier version of this document said the member alone governed their sharing and
> that there was no admin override at all. That is now narrowed: a family's head or spouse
> holds *permission*, the member holds *consent*, and both are required. The property worth
> preserving — that no
> administrator can cause a person to broadcast their location — is unchanged, and is stated
> explicitly in HS-9 and in the permissions table below.

### Holiday: everything else keeps working

**HS-12 — As a member, I can still add suggestions during Holiday.**
- Creating suggestions, voting, and commenting all remain available in Holiday.
- Suggestions still require confirmation by the owner or an organiser to reach the itinerary —
  Holiday changes nothing about that flow.

### End: archive

**HS-13 — As any member, I can browse the finished trip as an archive.**
- The archive view combines the map (itinerary pins, check-in pins, routes), the day-by-day
  itinerary, the check-in feed, and photos, all read-only.
- Every create/edit/delete control is absent from the UI and rejected by the server.
- The archive is readable on mobile and desktop and needs no special permissions beyond membership.

**HS-14 — As a member, I get a clear explanation when I try to change something in End.**
- Any blocked mutation returns a specific error identifying the stage as the reason.
- The UI surfaces this as an inline message, not a generic failure toast.

## Permissions

| Capability | Owner | Organiser | Head | Spouse | Member | Logged-out |
|---|---|---|---|---|---|---|
| View current stage | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Advance stage (planning→holiday→end) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Revert stage (one step back) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| View now/next screen | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Create own check-in | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| View check-in feed + pins | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Delete own check-in | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Delete anyone's check-in | ✅ (any) | ✅ (any) | ✅ (own family only) | ✅ (own family only) | ❌ | ❌ |
| Toggle own live-location sharing | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| View others' live locations | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Hide a family from the map | ✅ (any) | ✅ (any) | ✅ (own family) | ✅ (own family) | ❌ | ❌ |
| Hide one member from the map | ✅ (any) | ✅ (any) | ✅ (own family, incl. spouse) | ✅ (own family except the head) | ❌ | ❌ |
| Set a family's new-member default | ✅ (any) | ✅ (any) | ✅ (own family) | ✅ (own family) | ❌ | ❌ |
| **Turn on another user's sharing** | **❌** | **❌** | **❌** | **❌** | **❌** | **❌** |
| View End-stage archive | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |

Nobody — owner and organisers included — can turn on another person's live-location sharing, or
read a location for a user who is not sharing. Admins can only ever *remove* someone from the
map.

The "hide one member" row carries the head/spouse asymmetry from `plan/overview.md`'s Roles
section: a spouse can hide any other member of the family, and can set the family-wide switch
and the default for new members, but cannot flip the head's own per-member visibility switch —
that one is "the head's switch" and a spouse cannot change it, full stop (see the NOTE under
HS-15). The owner and organisers are exempt from that asymmetry — it is a family-internal rule
between a head and a spouse, not a trip-level one.

The admin/organiser/head/spouse rows above are permission, not consent: each is an independent
veto over a marker, and a marker requires every veto to be clear **and** the member's own
toggle to be on **and** a fresh position from their own browser. The settings themselves are
owned by `plan/features/families/` (FM-15); they are listed here because this is the feature
where their effect is visible.

## Stage availability

| Capability | Planning | Holiday | End |
|---|---|---|---|
| Stage advance (by owner or organiser) | ✅ → holiday | ✅ → end | ❌ (terminal) |
| Stage revert (by owner or organiser) | ❌ | ✅ → planning | ✅ → holiday |
| Now / next screen | Hidden (itinerary view instead) | ✅ default mobile screen | ❌ (archive instead) |
| Create check-in | ❌ | ✅ | ❌ |
| View check-ins | n/a (none exist) | ✅ | ✅ read-only |
| Live location sharing | ❌ | ✅ | ❌ (any rows purged) |
| Create/edit suggestions | ✅ | ✅ | ❌ |
| Vote / comment | ✅ | ✅ | ❌ |
| Admin confirm into itinerary | ✅ | ✅ | ❌ |
| Archive view | ❌ | ❌ | ✅ |

All of the above is enforced by FastAPI stage-guard dependencies, not by hiding UI.

## Out of scope (v1)

- Background or always-on location tracking of any kind (the web platform cannot do it; we will
  not simulate it with periodic pings or push wake-ups).
- Geofencing, arrival detection, ETA-to-next-item calculations, or "who is closest" analytics.
- Location history / breadcrumb trails (`live_locations` holds one current row per user only).
- A separate "status" model (running late / on my way / arrived) — presets on check-ins cover it.
- Sharing location with anyone outside the trip, or public/anonymous archive links.
- Offline check-in queueing (see `plan/features/pwa-push/` — offline is read-only in v1).
- Expenses in the archive view (post-v1; `overview.md` lists expenses as a later addition).
- Multiple concurrent trips in Holiday at once in the v1 UI (schema supports it; UI shows one).
- Automatic stage transitions based on `trips.start_date` / `end_date` — always a human decision.
