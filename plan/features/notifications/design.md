# notifications — Design

**Read first:** `plan/overview.md`, `plan/architecture.md`, `plan/design-system.md`, `CLAUDE.md`,
and this feature's `requirements.md`.

## Data model

### Existing table (from `plan/architecture.md`)

**`notifications`** — `id`, `created_at`, `updated_at`, plus:

| Column | Use |
|---|---|
| `recipient_user_id` | Owner. Every query is scoped to the session user by this column. |
| `type` | Event discriminator (see the type registry below). |
| `payload_json` | Deep-link target and render data. |
| `read_at` | Nullable. Null = unread. This is the only mutable field. |

One row per recipient per event. A suggestion approved in a nine-person trip creates nine rows. This
is intentional: read state is per-person, and the row count at family scale is trivial.

Indexes required:
- `(recipient_user_id, created_at DESC)` — the list query.
- Partial index on `(recipient_user_id) WHERE read_at IS NULL` — the badge count query.

### `payload_json` contract

Every payload carries enough to render the row **without** joining to the subject, so a deleted
subject still produces a readable notification.

```json
{
  "trip_id": "uuid",
  "subject_type": "suggestion|poll|comment|itinerary_item|trip",
  "subject_id": "uuid",
  "parent_type": "suggestion|poll|itinerary_item|null",
  "parent_id": "uuid|null",
  "actor": { "id": "uuid", "display_name": "Sam" },
  "summary": { "title": "Tintagel Castle", "extra": "3 new votes" },
  "deep_link": "/suggestions/{id}?panel=open",
  "category": "decisions|votes|mentions|itinerary|stage|nudges",
  "push_worthy": true
}
```

- `actor` is denormalised so a removed user does not break the row.
- `deep_link` is a **relative path**, generated server-side, so the same value works for the
  dropdown, the full list page, and (later) a push notification click.
- `category` is stored in the payload as well as being derivable from `type`, so preference filtering
  and later analytics do not need a lookup table in the database.
- `push_worthy` is read by `plan/features/pwa-push/` to decide whether to send a push. This feature
  sets it; it does not send anything.

### Type registry

| `type` | Category | `push_worthy` | Subject | Deep link |
|---|---|---|---|---|
| `suggestion.created` | decisions | false | suggestion | `/suggestions/{id}` |
| `suggestion.vote_summary` | votes | false | suggestion | `/suggestions/{id}` |
| `suggestion.approved` | decisions | **true** | suggestion | `/suggestions/{id}` |
| `suggestion.rejected` | decisions | **true** | suggestion | `/suggestions/{id}` |
| `comment.mention` | mentions | **true** | comment | `/{parent_type}/{parent_id}#comment-{id}` |
| `comment.reply` | mentions | false | comment | `/{parent_type}/{parent_id}#comment-{id}` |
| `poll.opened` | decisions | false | poll | `/polls/{id}` |
| `poll.closed` | decisions | **true** | poll | `/polls/{id}` |
| `poll.nudge` | nudges | false | poll | `/polls/{id}` |
| `suggestion.nudge` | nudges | false | suggestion | `/suggestions/{id}` |
| `itinerary.changed` | itinerary | **true** | itinerary_item | `/itinerary?item={id}` |
| `stage.changed` | stage | **true** | trip | `/trip` |

Adding a type means adding a row here, an icon, and a copy string — nothing structural.

### PROPOSED ADDITION — `notification_preferences`

`user_settings` (per `plan/architecture.md`) has only `live_location_enabled` and `push_enabled`;
there is no place to store per-category opt-outs required by **N-10**.

```
notification_preferences
  id                uuid pk
  user_id           uuid fk -> users, not null
  category          text not null   -- decisions|votes|mentions|itinerary|stage|nudges
  enabled           bool not null default true
  created_at, updated_at
  unique (user_id, category)
```

Rationale for a table rather than six boolean columns on `user_settings`: categories will grow, and a
row-per-category avoids a migration each time. Absence of a row means **enabled** — no backfill is
needed, and new categories default on for existing users automatically.

NOTE: this is a proposed schema addition not present in `plan/architecture.md`. If it is accepted,
`plan/architecture.md`'s schema section should be updated in the same commit as the migration, per
the docs-first rule in `CLAUDE.md`.

### Email readiness (no work in v1)

`type` + `payload_json` already contain the actor, subject, summary, and a link. A future email
renderer needs only a template per `type` and a delivery service; **no schema change is required**.
Two things are deliberately left undone in v1: there is no `emailed_at` column and no user email
address on `users`. Both are additive later.

## Generation

### Where notifications are created

A single service, `server/app/services/notifications.py`, exposes:

```
create(recipients, type, payload) -> list[Notification]
notify_trip(trip_id, type, payload, exclude_user_ids=[])
```

Feature routers call this service; they never insert `notifications` rows directly. The service:

1. Expands the recipient list (trip members, thread participants, mentioned users).
2. Removes the actor — **you are never notified of your own action**.
3. Filters recipients by `notification_preferences` for the payload's category.
4. Applies the de-duplication window (below).
5. Inserts rows and broadcasts `notification.new` to each recipient's sessions.

Creation happens **inside the same transaction** as the triggering change, so a rolled-back approval
never leaves an orphan notification. The websocket broadcast happens after commit.

### De-duplication and collapsing (N-8)

| Rule | Window | Mechanism |
|---|---|---|
| Vote summary per suggestion per recipient | 6h | Before inserting, look for an unread `suggestion.vote_summary` for the same `subject_id` inside the window; if found, update its `payload_json.summary.extra` and `created_at` instead of inserting. |
| Itinerary changes | 15m | Same pattern with `itinerary.changed`, collapsing to "Itinerary updated (N changes)". |
| Nudges | 24h per subject per user | Hard rate limit; a repeat request returns a count of zero sent. |

Collapsing only ever merges into an **unread** row. Once you have read it, the next event produces a
fresh notification — otherwise updates would silently vanish.

### Nudges

The main admin triggers a nudge from a poll or suggestion. The server computes non-voters
(trip members with no `poll_scores` / `suggestion_votes` row for the subject), excludes those who
disabled the `nudges` category or were nudged within 24h, and creates rows for the remainder. The
response reports how many were notified and how many were skipped, so the UI can be honest.

## REST endpoints

All under `/api/v1/`, session cookie auth, CSRF on mutations.

| Method | Path | Request | Response | Dependencies |
|---|---|---|---|---|
| `GET` | `/notifications` | `?cursor=&limit=20&filter=all\|unread` | `{ items: Notification[], next_cursor, unread_count }` | `require_member`, scoped to session user |
| `GET` | `/notifications/unread-count` | — | `{ unread_count }` | `require_member` |
| `POST` | `/notifications/{id}/read` | — | `{ id, read_at, unread_count }` | `require_member` + ownership |
| `POST` | `/notifications/read-all` | `{ before?: iso8601 }` | `{ marked, unread_count }` | `require_member` |
| `GET` | `/notification-preferences` | — | `{ categories: { decisions: true, … } }` | `require_member` |
| `PUT` | `/notification-preferences` | `{ categories: { votes: false } }` | full updated map | `require_member` |
| `POST` | `/polls/{id}/nudge` | — | `{ notified, skipped }` | `require_main_admin`, `require_stage("planning","holiday")` |
| `POST` | `/suggestions/{id}/nudge` | — | `{ notified, skipped }` | `require_main_admin`, `require_stage("planning","holiday")` |

Notes:
- There is **no** `user_id` query parameter anywhere. Ownership is implicit in the session.
- `POST /{id}/read` on a notification belonging to someone else returns **404**, not 403 — a user
  should not be able to probe for the existence of other people's notifications.
- Read endpoints and the read-marking endpoints carry **no stage guard** (see `requirements.md`).
  Nudge endpoints do.
- `read-all` accepts an optional `before` timestamp so "mark all read" cannot accidentally clear a
  notification that arrived after the user clicked.
- Every response that changes read state returns the recomputed `unread_count`, so the client never
  has to guess or issue a second request.

`Notification` response shape:
```json
{ "id": "uuid", "type": "suggestion.approved", "category": "decisions",
  "created_at": "iso", "read_at": null,
  "actor": { "id": "uuid", "display_name": "Sam" },
  "title": "Sam approved Tintagel Castle",
  "body": "It's now on the itinerary for Tue 14 Jul",
  "deep_link": "/suggestions/…", "subject_type": "suggestion", "subject_id": "uuid" }
```

`title` and `body` are rendered **server-side** from `type` + `payload_json`. This keeps copy in one
place and means a later email renderer reuses the same functions.
NOTE: this puts user-facing copy on the server, which is a slight departure from keeping strings in
the web app. It is deliberate — duplicating notification copy across the dropdown, the list page, and
push payloads is how those three drift apart.

## WebSocket events

Delivered over the single socket described in `plan/architecture.md`, but addressed to a
**per-user room** rather than the trip room, because notifications are private.

| Event | Payload | When | Sent to |
|---|---|---|---|
| `notification.new` | `{ notification: Notification, unread_count }` | A row is created for this user | All of that user's sessions |
| `notification.read` | `{ ids: [uuid], unread_count }` | One or more rows marked read | All of that user's sessions |
| `notification.updated` | `{ notification, unread_count }` | An unread row was collapsed/updated in place | All of that user's sessions |

**Cross-tab and cross-device sync (N-6)** is achieved entirely by these events being sent to *every*
session of the user, including the one that performed the action. The acting tab has already applied
its optimistic update and reconciles idempotently; other tabs learn from the event. No
`BroadcastChannel` or storage-event hack is needed, and it works across devices, which a same-browser
mechanism could not.

**Reconnect:** `plan/architecture.md` specifies the client sends its last-seen notification id on
resume. The server replies with any notifications created since, plus the authoritative
`unread_count`. If the gap is larger than a threshold (e.g. 100), the server instructs a full refetch
instead of replaying.

## UI behaviour

Per `plan/design-system.md` — semantic tokens only, light and dark both working, ≥44px touch targets.

### Bell and badge

- Bell sits in the app shell header (desktop) and in the top bar on mobile.
- Badge: a small pill on the bell, showing the number, capped at "9+". Uses `--color-danger` surface
  with guaranteed AA contrast text, and the count is also in the accessible name of the button.
- Badge appears/disappears with a 150–250ms transition; respects `prefers-reduced-motion`.
- Initial count comes from the page bootstrap payload, not a separate round trip, so the badge is
  correct before the websocket connects.

### Dropdown

- Anchored popover on desktop (~380px wide, max ~70vh, internal scroll); a **bottom sheet** on mobile,
  per the mobile pattern in `design-system.md`.
- Header: "Notifications" + "Mark all as read" (disabled when the count is zero).
- Rows: type icon in a leading slot, title (semibold), body (muted, one line, ellipsised), relative
  timestamp right-aligned with tabular figures, and an unread dot.
- Unread rows use a raised surface token **plus** the dot **plus** heavier title weight — three
  signals, so colour is never doing the work alone.
- Full-row click target; a secondary "mark read" control appears on hover/focus and is always present
  on touch.
- Skeleton rows on first open (structural load); "Load older" button at the bottom, replaced by a
  spinner only while that sub-second fetch is in flight.
- Empty state: an illustration-light message — "Nothing new. You're all caught up." — per the
  empty-state rule.
- Escape closes; focus returns to the bell; arrow keys move between rows; Enter activates.

### Full list page

- `/notifications` route with the same rows at page width, a filter for All / Unread, and infinite
  scroll. Primarily for mobile and for catching up after a few days away.

### Deep-link behaviour

- Clicking a row: optimistically mark read → close the panel → navigate.
- Suggestion/poll links open the entity's **side panel** (desktop) or **bottom sheet** (mobile) over
  the map — consistent with the rest of the product, rather than a separate page.
- Comment links navigate to the parent, scroll the comment into view, and apply a brief highlight
  (motion respects reduced-motion; the highlight also uses an outline, not only a background tint).
- Itinerary links open the itinerary with the item selected and the timeline scrubbed to it.
- Stage links open the trip screen.
- Missing subject → an inline "This is no longer available" panel state, and the notification stays
  marked read.

### Preferences UI

- Six labelled switches in settings with one line of explanation each.
- The **mentions** switch shows a warning caption when turned off: "You won't be told when someone
  asks you something directly."
- Changes save immediately with a toast confirming the change (a transient confirmation of the user's
  own action — the correct use of a toast).

### Relationship to toasts

Toasts are **never** used to deliver a notification. If a `notification.new` arrives while the user is
looking at the app, the badge increments and, at most, the bell plays a subtle attention animation.
Information that must persist lives in the list. This is a direct rule from `design-system.md`.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| User has 500 unread | Badge shows "9+"; list pages normally; `read-all` handles them in one statement. |
| `read-all` while new notifications are arriving | The `before` timestamp bounds the operation; anything newer stays unread. |
| Mark-read request fails | Optimistic update rolls back, the row returns to unread, and an inline error appears in the panel (not a toast). |
| Notification for a deleted suggestion | Row still renders from `payload_json`; clicking shows the "no longer available" state. |
| Actor user deleted | `actor.display_name` from the payload still renders; no join, no crash. |
| User disabled a category, then re-enables it | Only future events produce rows; nothing is backfilled. This is stated in the settings copy. |
| Websocket down | Badge falls back to polling `/notifications/unread-count` every 60s while disconnected, and stops polling on reconnect. |
| Reconnect after a long absence | Server instructs a full refetch when the gap exceeds the threshold, rather than replaying hundreds of events. |
| Two tabs both press "Mark all as read" | Idempotent; the second returns `marked: 0` and the same `unread_count`. |
| Nudge pressed twice | Second call reports `notified: 0, skipped: N` and the UI says "Everyone was nudged recently". |
| Nudge with zero non-voters | Control is disabled with the caption "Everyone has voted". |
| Notification created inside a transaction that rolls back | No row exists and no event is broadcast, because the broadcast is post-commit. |
| Trip in `end` stage | Read/mark-read still work; only the stage-change notification is generated; nudge endpoints return 409 `stage_forbidden`. |
| Very long title/body | Server truncates `summary` fields at generation time; the UI ellipsises with the full text available in the row's title attribute. |
| Retention | A scheduled task deletes read notifications older than 90 days and unread ones older than 180 days. No user-facing delete exists; this keeps the table bounded without giving users a management chore. |
