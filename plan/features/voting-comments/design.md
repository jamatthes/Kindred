# voting-comments — Design

Implements `requirements.md` in this directory. Read `plan/architecture.md` and
`plan/design-system.md` first. Closely coupled to `plan/features/map-suggestions/` — that
feature owns the suggestion record and its status *field*; this feature owns the status
*transitions* and their UI.

---

## Data model

### `suggestion_votes` (exists in `architecture.md`, used as-is)

| Column | Use here |
|---|---|
| `id` | uuid pk |
| `suggestion_id` | FK, indexed |
| `user_id` | FK |
| `score` | int 0–10, non-null in score mode, null in thumbs mode |
| `thumb` | `up` / `down`, non-null in thumbs mode, null in score mode |
| `created_at` / `updated_at` | standard |

Unique constraint on `(suggestion_id, user_id)` — this is what makes "one vote per user"
structural rather than a race-prone application check. Voting is an **upsert** on that
constraint; clearing a vote deletes the row.

Exactly one of `score` / `thumb` is populated per row. Enforced by a check constraint:
`(score IS NULL) <> (thumb IS NULL)`.

### `trip_category_settings` (exists, read-only here)

`(trip_id, category, voting_mode)` where category is
`poll`/`region`/`accommodation`/`activity`/`meal` and mode is `score`/`thumbs`. A
suggestion's mode is resolved by looking up the row for its `type`. The mode is **not**
denormalised onto the vote row — it is always derived, so a settings change never leaves
stale mode data behind.

### `comments` (exists, one PROPOSED ADDITION)

| Column | Use here |
|---|---|
| `id` | uuid pk |
| `subject_type` | `suggestion` / `poll` / `itinerary_item` |
| `subject_id` | uuid of the subject; no FK, polymorphic |
| `author_id` | FK to users |
| `body` | plain text with mention markup |
| `edited_at` | nullable; set on edit, drives the "edited" marker |
| `created_at` / `updated_at` | standard |

**PROPOSED ADDITION — `comments.deleted_at` (timestamptz, nullable, default null).**

Rationale: `design-system.md` mandates *undo over confirm* for low-stakes destructive actions
and names "delete own comment" as the example. A hard `DELETE` cannot be undone, so the undo
window would have to live entirely in the client — meaning a closed tab, a crash, or a
navigation during the window loses the comment irrecoverably, and other users watching the
thread would see it vanish and reappear with no server-side truth. A `deleted_at` soft delete
makes undo a real server operation: delete sets the timestamp, undo clears it, and a periodic
cleanup hard-deletes rows past the window.

Consequences:
- Every read filters `deleted_at IS NULL`.
- An index on `(subject_type, subject_id, created_at) WHERE deleted_at IS NULL` serves thread
  reads.
- A maintenance task hard-deletes rows where `deleted_at` is older than the retention window
  (target 30 days) so this does not become an accidental permanent archive of deleted text.
- The undo *affordance* is much shorter than the retention window (target 10 seconds) — the
  retention window exists for safety and support, not as a user-facing feature.

NOTE: the alternative considered was a purely client-side undo timer with a delayed hard
delete. It was rejected for the durability reasons above.

### `notifications` (exists, written here)

Mentions insert one row per mentioned user: `recipient_user_id`, `type = 'mention'`,
`payload_json` carrying the deep-link target (`subject_type`, `subject_id`, `comment_id`,
plus author display name for the list rendering), `read_at` null. Delivery and the bell UI
belong to the `notifications` feature; this feature only creates the rows and emits the event.

### Mention markup

Stored inline in `body` as `@[Display Name](user:<uuid>)`. Storing the uuid means a display
name change does not orphan the mention, and rendering never needs a lookup table parse.
The parser extracts uuids on save to decide who gets notified; unknown or off-trip uuids are
rendered as plain text and notify nobody.

---

## REST endpoints

All under `/api/v1`, Pydantic schemas both directions, session auth, CSRF on mutations.

### `PUT /api/v1/suggestions/{id}/vote`
Upsert the calling user's vote. `PUT` because it is idempotent — the same body twice leaves
the same state.

Request: `{ score }` **or** `{ thumb }`. The server resolves the suggestion's category mode
and rejects the field that does not match with `422` ("this category uses thumbs voting").

Response: the updated tally plus `my_vote`:
```
{ mode, count, eligible_count,
  average?, distribution?: [c0..c10],     // score mode
  up?, down?, none?,                       // thumbs mode
  my_vote: { score? , thumb? } | null,
  voters: [ { user_id, display_name, family_id, family_color, score?, thumb? } ],
  not_voted: [ { user_id, display_name, family_id } ] }
```
Permission: `require_member`. Stage: `require_stage("planning", "holiday")`.
Emits `suggestion.vote.updated`.

### `DELETE /api/v1/suggestions/{id}/vote`
Clears the calling user's vote (deletes the row). Returns the same tally shape.
Permission: `require_member`. Stage: planning/holiday. Emits `suggestion.vote.updated`.

### `GET /api/v1/suggestions/{id}/votes`
Returns the tally shape above. Permission: `require_member`. Available in every stage.

### `GET /api/v1/me/pending-votes`
Query: `trip_id`.
Response: `{ count, suggestion_ids: [...] }` — suggestions in the trip that the caller has
not voted on, excluding `rejected` ones and, by default, the caller's own suggestions
(`exclude_own=false` overrides). Permission: `require_member`.

### `GET /api/v1/comments`
Query: `subject_type`, `subject_id`. Returns the flat thread ordered by `created_at`,
filtered to `deleted_at IS NULL`.
Response per comment: `id, author { user_id, display_name, family_id, family_color }, body,
mentions: [user_id], edited_at, created_at, can_edit, can_delete`.
`can_edit` / `can_delete` are computed server-side for the calling user so the client never
re-derives permissions. Permission: `require_member`.

### `POST /api/v1/comments`
Request: `subject_type, subject_id, body`.
Validates that the subject exists and belongs to a trip the caller is a member of — the
polymorphic `subject_id` has no FK, so this check is mandatory, not optional.
Parses mentions, inserts notification rows for on-trip mentioned users other than the author.
Permission: `require_member`. Stage: planning/holiday.
Emits `comment.created`, and `notification.new` to each mentioned user.

### `PATCH /api/v1/comments/{id}`
Request: `body`. Sets `edited_at`. Re-parses mentions; **newly added** mentions notify, and
already-notified users are not re-notified (compare against the previous mention set).
Permission: author only — `require_comment_author(id)`. No admin override exists, by design.
Stage: planning/holiday. Emits `comment.updated`.

### `DELETE /api/v1/comments/{id}`
Soft-deletes by setting `deleted_at`.
Permission: `require_can_delete_comment(id)` — author, family admin of the author's family,
or main admin. Stage: planning/holiday. Emits `comment.deleted`.

### `POST /api/v1/comments/{id}/undo-delete`
Clears `deleted_at`. Permitted only to the user who performed the delete and only while the
row is inside the retention window; otherwise `404`. Stage: planning/holiday.
Emits `comment.created` (a restore is indistinguishable from a create for consumers, which
keeps client reconciliation simple — it reconciles by `id`).

### `PATCH /api/v1/suggestions/{id}/status`
Owned by `map-suggestions` (defined in its `design.md`); consumed here as the backing call
for the admin controls. `require_main_admin`, transition table validated server-side,
`scheduled` rejected with `422`. Emits `suggestion.status_changed`.

### `GET /api/v1/trips/{id}/category-settings` and `PATCH .../category-settings`
Reading is `require_member` (the client needs the mode to render the right control).
Writing is `require_main_admin` and owned by `admin-console`; referenced here because a mode
change has consequences described below.

---

## WebSocket events

### Emitted
| Event | Payload | When |
|---|---|---|
| `suggestion.vote.updated` | `suggestion_id`, full tally (without `my_vote`) | any vote upsert or clear |
| `comment.created` | full comment object | post or undo-delete |
| `comment.updated` | full comment object | edit |
| `comment.deleted` | `id`, `subject_type`, `subject_id` | soft delete |
| `notification.new` | notification row | mention created |

`my_vote` is deliberately excluded from the broadcast payload — it is per-recipient, and each
client already knows its own vote. Clients merge the broadcast tally with their local
`my_vote`.

### Consumed
| Event | Effect |
|---|---|
| `suggestion.status_changed` | restyle admin controls and status chip in the open panel |
| `suggestion.deleted` | close the panel if it was showing that subject; drop its thread |
| `stage.changed` | re-evaluate whether vote/comment inputs render at all |

---

## UI behaviour

### Where things appear
Per the progressive disclosure ladder in `design-system.md`:

- **List row** — compact tally (a number plus a minimal bar), comment count.
- **Popover card** (map pin click) — tally widget at medium density, comment count, no input.
  Cards stay glanceable.
- **Side panel / bottom sheet** — the working surface: full tally with voter attribution, the
  vote control, the comment thread with composer, and the admin controls.

Voting is possible from the popover card as well as the panel, because a quick pass over many
pins is a real workflow. Commenting is panel-only.

### Vote controls
- **Score mode** — a 0–10 control. Values are labelled with digits; the preference ramp
  (`--scale-pref-0…10`, colourblind-safe red → amber → teal-green) tints the control, and the
  chosen number always renders as text beside it. Colour never carries the value alone.
- **Thumbs mode** — two clearly-labelled buttons with icons, current state distinct from
  unvoted, and a third "clear" affordance once a vote exists.
- Hit targets ≥ 44 px on touch. Full keyboard operation: arrow keys move along the score
  scale, Enter commits.

### Tally widgets
From `web/src/charts/`, per `design-system.md` — no chart library, honesty rules built in.

- **Score mode** → `AvgBar` for the average, `SpreadDots` in the panel for the disagreement
  view (one dot per member on a 0–10 axis). Bars start at zero; the API has no baseline prop.
- **Thumbs mode** → `DistributionStrip` showing up/down/none proportions.
- Widgets take `insight` as their title prop to nudge stating the finding
  ("Splits the group — 4 for, 3 against") rather than the metric name.
- "Not yet voted" is always shown as its own proportion, never folded into a denominator that
  hides it. A 10/10 average from one voter must not look like consensus.

### Optimistic UI
Voting and commenting apply immediately per `design-system.md`:
1. Apply locally and mark the item pending.
2. Fire the request.
3. On success, reconcile with the authoritative tally.
4. On failure or WS error, roll back visibly and surface a toast — toasts are for transient
   confirmation and failure of *your own* actions only.
5. On reconnect, refetch the tally and thread for the open subject and reconcile by `id`.

### Comment thread
- Flat list, oldest first, author display name with family colour accent, relative timestamp,
  "edited" marker when `edited_at` is set.
- Composer at the bottom; `@` opens a member picker; the mention renders as a distinct token.
- Own comments carry edit and delete affordances derived from `can_edit`/`can_delete`.
- **Delete → undo**: the comment collapses out immediately with an inline undo affordance for
  ~10 seconds. The undo lives in the thread where the comment was, not only in a toast, so it
  survives the user looking elsewhere.
- Admin deletion of another person's comment uses a confirm dialog and leaves a "comment
  removed" tombstone rather than silently reflowing the thread.
- Empty state: "No comments yet — start the discussion", composer inline.

### Admin controls (main admin only)
A distinct block at the bottom of the side panel, visually separated so it reads as a
different kind of authority from ordinary member actions.

- Buttons for the transitions valid from the current status; invalid ones are absent, not
  disabled-and-mysterious.
- **Reject opens a real confirm dialog** naming the suggestion and stating that it will be
  hidden from the default list. This is the admin-destructive case `design-system.md`
  reserves confirms for.
- Approve and shortlist commit directly — they are reversible, so a confirm would be friction
  without value.
- The whole block does not render for non-admins. Enforcement is server-side regardless.

### "What needs my vote"
- A count in the trip chrome, fed by `GET /api/v1/me/pending-votes`.
- Activating it applies a filter chip to the suggestion list (shared filter state with
  `map-suggestions`) and marks the matching pins on the map.
- The count refreshes on `suggestion.vote.updated` and `suggestion.created`.
- Empty state when the count is zero: "You're all caught up" — the affordance stays visible
  but quiet rather than disappearing.

### Styling and motion
Token-only; both themes checked. The preference ramp is defined once as tokens and reused
identically by map tints, table heat cells, and chart fills so all three read the same.
Motion 150–250 ms for comment-in, undo-collapse, and tally transitions; suppressed under
`prefers-reduced-motion` (a tally that animates its bar must snap instead).

---

## Voting mode changes with existing votes

The main admin can change a category's `voting_mode` after voting has begun. The rule:

**Existing vote rows are preserved. Nothing is deleted or converted.**

- The admin sees a warning before committing: "12 votes already exist in this category. They
  will be kept but shown in the new mode."
- Rendering after a switch:
  - **score → thumbs**: a stored `score` renders as up when ≥ 6, down when ≤ 4, and as
    "unclear" when exactly 5. The tally labels these as converted so the display is not
    passed off as a genuine thumbs vote.
  - **thumbs → score**: a stored `thumb` has no defensible numeric value, so it is **not**
    invented. Those users are shown as "not yet voted" in the new mode, with their thumb
    preserved in the row and visible in the voter attribution list.
- A user who re-votes after a mode change writes the new mode's column; the server clears the
  other column in the same upsert so the check constraint holds.
- Switching back restores the original display, because the underlying rows were never lost.

NOTE: fabricating a 0–10 score from a thumb would put invented data into an average and
violate the honesty rules in `design-system.md`. Showing those members as outstanding is the
honest option and prompts them to re-vote.

---

## Edge cases and error states

| Case | Handling |
|---|---|
| Two rapid votes from the same user | Upsert on the unique constraint; last write wins. No duplicate rows are structurally possible. |
| Vote submitted in the wrong mode | `422` naming the category's actual mode; the client refetches settings in case it was stale. |
| Vote on a `rejected` suggestion | Allowed but discouraged — rejected items are filtered out by default, so this only happens via a deep link. The tally still records it, since a rejection may be reopened. |
| Vote on a `scheduled` suggestion | Allowed. The decision is already made, but the record stays honest about how the group felt. |
| Voting mode changed mid-session | `trip_category_settings` is re-read on `suggestion.vote.updated` failure; the control re-renders in the correct mode without a page reload. |
| Comment on a subject that was deleted meanwhile | `404` on post; the client closes the thread and shows "This item was removed". |
| Comment subject belongs to another trip | `403` from the subject-ownership check — mandatory because `subject_id` has no FK. |
| Mention of a user not on the trip | Rendered as plain text; no notification row created. |
| Mention of self | Rendered normally; no self-notification. |
| Mention added during an edit | Only newly added mentions notify; the previous mention set is diffed to avoid re-pinging. |
| Undo after the retention window | `404`; the client shows "Too late to undo" and removes the affordance. |
| Undo pressed twice / by another user | Only the deleting user may undo, and only while soft-deleted; the second call is a no-op `404`. |
| Two admins act on status simultaneously | Server validates against the *current* status; the loser gets `409` with the current status, and the client re-renders from `suggestion.status_changed`. |
| Reject confirm dismissed | Nothing happens; no request fires. |
| Tally requested for a suggestion with no votes | Returns zeroed tally with `count: 0` and full `not_voted` list. Widgets render their empty state, never a misleading 0.0 average. |
| WebSocket disconnected during voting | Optimistic vote stays pending; on reconnect the tally is refetched and unacknowledged votes roll back visibly. |
| End stage reached while composing a comment | Guard rejects with `403`; the composer is replaced by the frozen-trip state and the draft is preserved in the client so nothing typed is silently lost. |
| Member removed from the trip after voting | Their vote rows remain (the group's history is real); their name still renders in attribution, marked as a former member. |
| Extremely long comment body | Length cap enforced in the Pydantic schema (target 4000 chars) with a counter in the composer near the limit. |

---

## NOTE (2026-08-12) — handoff from `map-suggestions`'s M3 web implementation

`SuggestionDetailPanel.tsx` (`web/src/features/map-suggestions/`) already renders
`vote_summary`/`comment_count` read-only and has explicit slots waiting for this feature:

- A `.sugg-detail__votes` block currently prints a plain average/tally string — replace with
  the real voting widget (score slider or thumbs, per `voting_mode`).
- A `.sugg-detail__comments-slot` div currently reads "N comments — the full thread arrives
  with `voting-comments`" — replace with the real comment thread component
  (`polls/CommentThread.tsx` is the pattern to follow; subject type is `suggestion`).
- Status confirm/reject buttons already exist in the panel (`STATUS_ACTIONS`, gated on
  `user.is_owner || user.is_organiser`) and call `PATCH /suggestions/{id}/status` directly —
  reusable as-is, or replace if this feature's own admin-bar pattern differs.
- `PopoverCard`'s `voteSummary`/`commentCount` props (pre-built, `features/map/PopoverCard.tsx`)
  are filled with a plain string today in the mobile `BottomSheet` peek snap
  (`MapSuggestionsScreen.tsx`) — same swap applies there.
