# voting-comments — Requirements

Feature 6 in `plan/overview.md`. Milestone M3.

Votes and discussion on suggestions, plus the admin controls that move a suggestion through
its status flow. This is how a group of families actually converges on a decision: everyone
registers a preference, the disagreement is visible rather than buried in a chat thread, and
the main admin makes the final call in the open.

## Concepts

- **Voting mode** — per category, configured by the main admin in `trip_category_settings`.
  Either **score** (0–10) or **thumbs** (up/down). A suggestion's mode is determined by its
  `type`; a poll's mode by the `poll` category row.
- **Vote** — one per user per suggestion, changeable at any time until the trip freezes.
- **Tally** — the aggregate view: average and distribution for score mode, up/down/none
  proportions for thumbs mode.
- **Comment** — free text attached polymorphically to a suggestion, a poll, or an itinerary
  item. May contain `@mentions`, which generate notifications.

## User stories

### V1 — Vote on a suggestion
**As a member, I can register my preference on any suggestion.**
- The control matches the mode configured for that suggestion's category: a 0–10 scale for
  score mode, up/down for thumbs mode.
- My vote appears immediately (optimistic), and rolls back visibly if the server rejects it.
- The control shows my current vote distinctly from the unvoted state.
- I cannot vote twice — voting again replaces my previous vote.

### V2 — Change or clear my vote
**As a member, I can change my vote or remove it entirely.**
- Re-voting overwrites; there is no history kept in v1.
- Clearing removes my row so I count as "not yet voted" again, which keeps the
  "needs my vote" affordance honest.

### V3 — See the tally live
**As a member, I can see how the group feels at a glance, updating as others vote.**
- Score mode shows an average with a distribution; thumbs mode shows up/down/none proportions.
- The numeric value always appears as text — never colour alone (see the preference ramp rule
  in `plan/design-system.md`).
- Tallies update over WebSocket without a refresh.
- The tally appears in three places at three densities: list row, popover card, side panel.

### V4 — See who voted what
**As a member, I can expand a tally to see individual votes attributed to people.**
- Votes are attributed, not anonymous — this is a family group, and hidden votes would make
  the disagreement view useless.
- Members who have not voted are listed as outstanding.

### V5 — Find what needs my vote
**As a member, I can quickly find the suggestions I have not voted on yet.**
- A count is visible in the trip chrome ("6 need your vote").
- Activating it filters the suggestion list to exactly those, and marks their pins on the map.
- Rejected suggestions and my own suggestions are excluded from the count by default.

### V6 — Comment on a suggestion, poll, or itinerary item
**As a member, I can discuss any of these in a thread attached to it.**
- The thread lives in the side panel / bottom sheet, beneath the record's details.
- Comments show author, family colour accent, body, and relative timestamp.
- New comments appear live for everyone viewing that subject.
- Threads are flat in v1 — one level, no nested replies.

### V7 — Mention someone
**As a member, I can type `@` to mention a trip member in a comment.**
- An autocomplete offers members of the trip.
- Saving the comment creates a notification for each mentioned user, deep-linked to the
  comment's subject.
- The mention renders as a distinct token in the comment body.
- Mentioning someone not on the trip is not possible through the picker; if such markup is
  typed manually it renders as plain text and generates no notification.

### V8 — Edit or delete my own comment
**As a member, I can edit or delete a comment I wrote.**
- An edited comment shows an "edited" marker (`edited_at`).
- Deleting is a low-stakes destructive action, so it uses **undo, not confirm**, per
  `plan/design-system.md`: the comment disappears immediately with an undo affordance for a
  short window, and only then becomes permanent.
- Undo restores the comment in place, preserving its original position in the thread.

### V9 — Confirm or reject a suggestion
**As the main admin, I can move a suggestion through its status flow from the side panel.**
- Controls: "Shortlist", "Approve", "Reject", and "Reopen" for a rejected suggestion.
- **Reject requires a real confirmation dialog** — it is an admin-destructive action, and
  `design-system.md` reserves confirms for exactly these.
- Approving does not schedule; scheduling onto a day is the itinerary feature's job.
- Status changes broadcast live and restyle pins and rows everywhere.
- The controls are invisible — not merely disabled — for non-admins.

### V10 — Moderate comments
**As the main admin, I can delete any comment; as a family admin, I can delete comments
written by members of my own family.**
- Admin deletion of someone else's comment uses a confirm dialog, not undo.
- The thread shows that a comment was removed rather than silently reflowing.

## Permissions

| Action | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| View tallies and who voted | Yes | Yes | Yes | No |
| Cast / change / clear own vote | Yes | Yes | Yes | No |
| Vote on behalf of someone else | No | No | No | No |
| View comment threads | Yes | Yes | Yes | No |
| Post a comment | Yes | Yes | Yes | No |
| Edit own comment | Yes | Yes | Yes | No |
| Delete own comment (undo pattern) | Yes | Yes | Yes | No |
| Delete a comment by own family member | Yes | Yes | No | No |
| Delete any comment | Yes | No | No | No |
| Shortlist / approve / reject a suggestion | Yes | No | No | No |
| Reopen a rejected suggestion | Yes | No | No | No |
| Change a category's voting mode | Yes | No | No | No |

NOTE: nobody may edit another person's comment — only delete it. Editing someone else's words
under their name is never appropriate, so the permission does not exist at any level.

Family admins can delete comments within their own family as a lightweight moderation path
that does not require pulling in the main admin. This is a deliberate extension of the
"family admin manages own family" principle in `overview.md`.

All checks are FastAPI dependencies. Frontend hiding is presentation only, never the control.

## Stage availability

| Stage | Behaviour |
|---|---|
| **Planning** | Full behaviour — vote, comment, mention, moderate, and confirm/reject. |
| **Holiday** | Unchanged. Suggestions keep arriving during the trip and still need votes and admin confirmation. |
| **End** | Frozen read-only. Tallies and threads remain fully readable as part of the archive; every mutation is rejected by the stage guard. No voting, commenting, editing, deleting, or status change. |

## Out of scope (v1)

- Nested/threaded replies beyond a single flat level.
- Emoji reactions on comments or suggestions.
- Attachments or images inside comments.
- Rich text or Markdown in comment bodies — plain text plus mention tokens only.
- Email notification of mentions (`overview.md` places email out of scope for v1; the schema
  allows it later). In-app and Web Push notifications are covered by `notifications`.
- Anonymous or secret voting.
- Weighted votes, per-family vote aggregation into a single family vote, or quorum rules.
- Vote history / audit trail of changed votes.
- Comment moderation queues, reporting, or profanity filtering.
- Mentioning a whole family or an `@everyone` token.
- Real-time typing indicators or read receipts on threads.
