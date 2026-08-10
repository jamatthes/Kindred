# notifications — Requirements

**Read first:** `plan/overview.md`, `plan/architecture.md`, `plan/design-system.md`, `CLAUDE.md`.
Milestone **M6**.

## Summary

An in-app notification centre following the **GitKraken pattern** named in `design-system.md`: a bell
icon in the app shell with an unread-count badge, opening a dropdown list of notifications. Every
notification deep-links to its subject. New notifications arrive live over the existing WebSocket, and
the unread badge stays in sync across every tab and device the user has open. Toasts are not part of
this feature — per `design-system.md`, toasts confirm *your own* transient actions and notifications
carry information that must persist.

**Email is explicitly out of scope for v1** (`overview.md` decision log). The schema is already
shaped so an email renderer can be added later without a migration.

## User stories

### The bell and the list

**N-1 — As a member, I can see how many unread notifications I have.**
- A bell icon is present in the app shell on every authenticated screen.
- An unread count badge appears when the count is greater than zero, showing "9+" above nine.
- The badge is not colour-only: it carries the number, and the bell has an accessible label reading
  e.g. "Notifications, 3 unread".
- The count is correct on page load without waiting for a websocket message.

**N-2 — As a member, I can open a dropdown and read my notifications.**
- Clicking the bell opens a panel listing my notifications, newest first.
- Each row shows: a type icon, a one-line human summary, the actor where relevant, and a relative
  timestamp ("12 min ago") with the absolute time on hover/long-press.
- Unread rows are visually distinct by both a marker dot and a weight/surface change — never colour
  alone.
- The list shows a designed empty state when I have no notifications.
- The panel is keyboard-navigable and dismissible with Escape.

**N-3 — As a member, I can load older notifications.**
- The dropdown loads a first page (20) and offers "Load older" / infinite scroll for more.
- A "See all" affordance opens a full-page notification list for longer browsing on mobile.
- Paging is stable while new notifications arrive (cursor-based, not offset-based).

**N-4 — As a member, I can mark notifications as read.**
- Clicking a notification marks it read and navigates to its subject.
- I can mark a single notification read without navigating, via a per-row control.
- "Mark all as read" clears the badge in one action.
- Marking read is optimistic and rolls back if the server rejects it.

**N-5 — As a member, clicking a notification takes me to exactly the right place.**
- Each notification deep-links to its subject: the suggestion's side panel, the poll, the specific
  comment (scrolled to and briefly highlighted), the itinerary item, or the trip screen for stage
  changes.
- If the subject no longer exists (deleted suggestion, removed comment), I get a clear
  "this is no longer available" state rather than a broken page, and the notification is still
  marked read.
- Deep links work when opened cold (pasted URL, or from a push notification later).

**N-6 — As a member with the app open in two places, my badge stays in sync.**
- Reading a notification on my phone clears it on my laptop within a second, without a refresh.
- Marking all read syncs the same way.
- After a websocket reconnect, the client resyncs so it never shows a stale count.

### What generates a notification

**N-7 — As a member, I am notified about things that concern me.**
The following events generate notifications:

| Event | Who is notified |
|---|---|
| New suggestion added | All trip members except the author |
| Vote summary / threshold reached on a suggestion | The suggestion's author and the main admin |
| Admin approved a suggestion | All trip members (the decision is group news) |
| Admin rejected a suggestion | The suggestion's author; main admin sees their own action only in the audit sense, not as a notification |
| @mention in a comment | Each mentioned user |
| Reply in a thread I participate in | Thread participants except the author |
| Poll opened | All trip members |
| Poll closed | All trip members |
| Nudge: "you haven't voted yet" | Members who have not voted on an open poll or an active suggestion |
| Itinerary changed (item added, moved, removed) | All trip members |
| Stage changed (including revert) | All trip members |

- I am never notified about my own action.
- Notifications are per-recipient rows — reading one does not affect anyone else.

**N-8 — As a member, I am not spammed.**
- Vote activity is summarised, not one notification per vote: a suggestion produces at most one
  vote-related notification per rolling window (default 6 hours).
- Rapid successive itinerary edits within a short window (default 15 minutes) collapse into one
  "itinerary updated" notification.
- Nudges are sent at most once per poll/suggestion per user, and only after a quiet period.

**N-9 — As a main admin, I can trigger a nudge.**
- From a poll or suggestion, the main admin can send a "you haven't voted" nudge to non-voters.
- The control states how many people will be notified before sending.
- Rate-limited so the same nudge cannot be sent repeatedly (default once per 24h per subject).

### Preferences

**N-10 — As a member, I can turn off categories of notification I don't care about.**
- Settings offer a simple on/off per broad category: **decisions**, **votes**, **mentions**,
  **itinerary**, **stage**, **nudges**.
- All categories default to on.
- Turning a category off stops new rows being created for me in that category; it does not delete
  existing ones.
- Mentions can be turned off, but the settings copy warns that I may miss being asked something
  directly.

## Permissions

| Capability | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| See own bell + badge | ✅ | ✅ | ✅ | ❌ |
| List own notifications | ✅ | ✅ | ✅ | ❌ |
| Mark own notification read / all read | ✅ | ✅ | ✅ | ❌ |
| Read anyone else's notifications | ❌ | ❌ | ❌ | ❌ |
| Set own notification preferences | ✅ | ✅ | ✅ | ❌ |
| Set someone else's preferences | ❌ | ❌ | ❌ | ❌ |
| Send a nudge to non-voters | ✅ | ❌ | ❌ | ❌ |
| Delete notifications | ❌ (nobody — retention is automatic) | ❌ | ❌ | ❌ |

Notifications are strictly private to their recipient. There is no admin view of another user's
notification list, and the list endpoint is always scoped to the session user — it does not accept a
`user_id` parameter at all.

## Stage availability

| Capability | Planning | Holiday | End |
|---|---|---|---|
| Bell, badge, list, mark read | ✅ | ✅ | ✅ |
| Preferences | ✅ | ✅ | ✅ |
| New notifications generated | ✅ | ✅ | Only the stage-change notification for entering/leaving `end` |
| Nudges | ✅ | ✅ | ❌ |

NOTE: mark-read is a mutation but is deliberately **not** stage-guarded. Freezing a trip must not
prevent someone from clearing their own badge — the read state is personal metadata, not trip content.

## Out of scope (v1)

- **Email notifications** of any kind, including digests and invitations by email. The schema is
  ready (`notifications.type` + `payload_json` carry everything a renderer needs) but no sending
  path exists in v1.
- SMS, Slack, Discord, or any third-party delivery channel.
- Web Push delivery — that lives in `plan/features/pwa-push/`, which consumes the notification rows
  this feature creates.
- Per-notification granularity in preferences (e.g. "mute this one thread"); only the six broad
  categories exist in v1.
- Quiet hours / do-not-disturb scheduling.
- Notification snoozing, pinning, or manual deletion.
- Read receipts visible to other users ("Sam saw this").
- Grouping/threading beyond the simple collapsing rules in N-8.
- Cross-trip notification inbox — v1 shows one trip.
