# voting-comments — Tasks

Ordered implementation checklist. Each phase ends with a `Verify:` line that must pass before
moving on. Read `requirements.md` and `design.md` in this directory first.

Prerequisites: `foundation`, `families`, and `map-suggestions` are complete.
`trip_category_settings` rows exist (seeded by `foundation` or `admin-console`).

---

## Phase 1 — Migrations

- [ ] Confirm `suggestion_votes` matches `plan/architecture.md`; create it if `foundation`
      did not: `id`, `suggestion_id` (FK, indexed), `user_id` (FK), `score` (int, nullable),
      `thumb` (varchar, nullable), `created_at`, `updated_at`.
- [ ] Add the unique constraint on `(suggestion_id, user_id)` — this is what makes one-vote-
      per-user structural rather than a race-prone application check.
- [ ] Add check constraints: `score BETWEEN 0 AND 10`, `thumb IN ('up','down')`, and
      `(score IS NULL) <> (thumb IS NULL)`.
- [ ] Confirm `comments` matches `architecture.md`; create it if absent.
- [ ] **PROPOSED ADDITION** — add `comments.deleted_at` (timestamptz, nullable, default null).
      Rationale is in `design.md`; do not skip it, the undo pattern depends on it.
- [ ] Add a partial index on `(subject_type, subject_id, created_at) WHERE deleted_at IS NULL`.
- [ ] Run `alembic upgrade head` then `alembic downgrade -1` to confirm the migration reverses.

`Verify:` `alembic upgrade head` succeeds on an empty database; in psql, an attempt to insert
two votes for the same `(suggestion_id, user_id)` fails on the unique constraint, and an
insert with both `score` and `thumb` set fails on the check constraint.

---

## Phase 2 — Models

- [ ] Add `server/app/models/vote.py` with the `SuggestionVote` model and relationships to
      `Suggestion` and `User`.
- [ ] Add `server/app/models/comment.py` with the `Comment` model. Because `subject_id` is
      polymorphic with no FK, add a module-level docstring stating that every read and write
      path must verify subject ownership explicitly.
- [ ] Add a default query helper that filters `deleted_at IS NULL`, and make it the obvious
      path so a raw query is the exception rather than the norm.
- [ ] Add `resolve_voting_mode(trip_id, category)` reading `trip_category_settings`. Never
      denormalise the mode onto a vote row — always derive.

`Verify:` `pytest server/tests/test_models_vote.py server/tests/test_models_comment.py` passes,
including a test that the default comment query excludes soft-deleted rows.

---

## Phase 3 — Schemas

- [ ] Add `server/app/schemas/vote.py`: `VoteIn` (exactly one of `score`/`thumb`),
      `TallyOut` (mode, count, eligible_count, average, distribution, up/down/none, my_vote,
      voters, not_voted), `PendingVotesOut`.
- [ ] Add `server/app/schemas/comment.py`: `CommentCreate`, `CommentUpdate`, `CommentOut`
      (with `can_edit` / `can_delete` computed server-side), `CommentListParams`.
- [ ] Enforce a body length cap (target 4000 chars) in the schema.
- [ ] Add the mention parser in `server/app/services/mentions.py`: extract uuids from
      `@[Display Name](user:<uuid>)`, return the set, and expose a diff helper for edits.
- [ ] Unit-test the parser: multiple mentions, malformed markup, a uuid that is not a trip
      member, duplicate mentions of the same user, and a mention of the author.

`Verify:` `pytest server/tests/test_schemas_vote.py server/tests/test_mentions.py` passes,
including rejection of a `VoteIn` carrying both `score` and `thumb`.

---

## Phase 4 — Vote service and router

- [ ] Add `server/app/services/votes.py` with `upsert_vote`, `clear_vote`, and `get_tally`.
- [ ] `upsert_vote` resolves the category mode, rejects a mismatched field with `422`, and
      writes via a database upsert on the unique constraint, clearing the opposite column in
      the same statement so the check constraint holds after a mode change.
- [ ] `get_tally` computes count, eligible_count, average and distribution (score) or
      up/down/none (thumbs), plus attributed `voters` and the `not_voted` list. Never fold
      "not voted" into the denominator — it is reported separately.
- [ ] Implement the mode-change display rules from `design.md`: score → thumbs converts by
      threshold and labels the conversion; thumbs → score shows those users as **not yet
      voted** and never fabricates a number.
- [ ] Add `get_pending_votes(user, trip)` excluding rejected suggestions and, by default, the
      caller's own.
- [ ] Add `server/app/routers/votes.py`: `PUT`/`DELETE /api/v1/suggestions/{id}/vote`,
      `GET /api/v1/suggestions/{id}/votes`, `GET /api/v1/me/pending-votes`.
- [ ] `require_member` plus `require_stage("planning","holiday")` on mutations; `GET` works in
      every stage.
- [ ] Broadcast `suggestion.vote.updated` to the trip room, **excluding `my_vote`** from the payload.

`Verify:` Start the API and use `/docs`: `PUT` a score vote and confirm the tally; `PUT` again
with a different score and confirm the count stays at 1; `PUT` a `thumb` on a score-mode
category and confirm `422`; `DELETE` the vote and confirm the user moves into `not_voted`.

---

## Phase 5 — Comment service and router

- [ ] Add `server/app/services/comments.py` with `list_thread`, `create`, `update`,
      `soft_delete`, `undo_delete`, and a `verify_subject_access(subject_type, subject_id, user)`
      helper that resolves the subject's trip and confirms membership.
- [ ] Call `verify_subject_access` on **every** path — there is no FK to protect this.
- [ ] `create` parses mentions and inserts one `notifications` row per on-trip mentioned user,
      excluding the author, with a deep-link payload.
- [ ] `update` sets `edited_at`, re-parses mentions, and notifies only newly added ones.
- [ ] `soft_delete` sets `deleted_at`; `undo_delete` clears it, permitted only to the deleting
      user and only inside the retention window, else `404`.
- [ ] Record who performed the delete so `undo_delete` can check it (a `deleted_by` column is
      not in the schema — hold it in the session/request layer, or add it as a second
      PROPOSED ADDITION if a server-side check proves necessary across sessions).
- [ ] Add a maintenance task that hard-deletes rows whose `deleted_at` is older than the
      retention window (target 30 days).
- [ ] Add `require_comment_author(id)` and `require_can_delete_comment(id)` dependencies in
      `deps.py` — the latter allows author, family admin of the author's family, or main admin.
- [ ] Add `server/app/routers/comments.py` with `GET`, `POST`, `PATCH`, `DELETE`, and
      `POST /{id}/undo-delete`; compute `can_edit`/`can_delete` per calling user in the response.
- [ ] Broadcast `comment.created` / `.updated` / `.deleted`, and `notification.new` per mention.
      An undo-delete broadcasts `comment.created` so clients reconcile by `id`.
- [ ] Register both routers in `main.py`.

`Verify:` In `/docs`: post a comment containing a mention and confirm a `notifications` row
appears for the mentioned user; `PATCH` it and confirm `edited_at` is set; `DELETE` it and
confirm `GET` no longer lists it; `POST .../undo-delete` and confirm it returns.

---

## Phase 6 — Server tests

- [ ] Vote happy paths in both modes; change a vote; clear a vote.
- [ ] Unique-constraint test: concurrent votes from the same user yield exactly one row.
- [ ] Mode-mismatch `422`; mode-change behaviour in both directions, asserting explicitly that
      **thumbs → score fabricates no numeric value** and lists those users as not voted.
- [ ] Tally correctness: average, distribution, up/down/none, and `not_voted` for a suggestion
      with partial participation.
- [ ] `pending-votes` excludes rejected suggestions and own suggestions by default.
- [ ] Comment permission matrix: author edits; non-author edit returns `403` at every role
      including main admin (nobody edits another's words); author deletes; family admin deletes
      within family; family admin outside family returns `403`; main admin deletes any.
- [ ] Subject-ownership test: commenting on a subject in another trip returns `403`.
- [ ] Mention tests: off-trip uuid notifies nobody; self-mention notifies nobody; edit notifies
      only newly added mentions.
- [ ] Undo tests: within window succeeds; outside window `404`; by a different user `404`.
- [ ] Stage-guard tests: in `end` stage every mutation is rejected while `GET` tally and
      thread still succeed.
- [ ] Status-transition tests for the admin controls, including a `409` when two admins race.

`Verify:` `pytest server/tests/test_router_votes.py server/tests/test_router_comments.py`
passes with the full permission matrix and mode-change cases green.

---

## Phase 7 — Chart widgets

- [ ] Add or extend `web/src/charts/AvgBar.jsx` — bars start at zero, no `baseline` prop
      exists, `insight` is the title prop.
- [ ] Add `web/src/charts/DistributionStrip.jsx` for thumbs: up / down / **none** as three
      visible proportions.
- [ ] Add or extend `web/src/charts/SpreadDots.jsx` for the panel disagreement view — one dot
      per member on a 0–10 axis.
- [ ] All three token-aware: colours, spacing, and type from semantic tokens so the theme
      switch is free. Use the shared `--scale-pref-0…10` ramp.
- [ ] Every widget renders its numeric value as text — colour is never the sole carrier.
- [ ] Empty state per widget for `count: 0`; never render a misleading `0.0` average.
- [ ] Under `prefers-reduced-motion`, bars snap rather than animate.

`Verify:` `npm test` in `web/` passes the chart tests, including a case asserting that a
zero-vote tally renders the empty state and that the numeric label is present in the DOM.

---

## Phase 8 — Vote UI

- [ ] Add `web/src/features/voting-comments/` with the API client and store.
- [ ] `ScoreVoteControl`: 0–10, digit-labelled, ramp-tinted, chosen value shown as text,
      arrow-key navigation with Enter to commit, ≥ 44 px touch targets.
- [ ] `ThumbsVoteControl`: labelled up/down with icons, distinct current state, clear
      affordance once a vote exists.
- [ ] Mode is resolved from `trip_category_settings` per the suggestion's type; on a `422`
      mode mismatch the client refetches settings and re-renders in the correct mode.
- [ ] Tally at three densities: compact in the list row, medium on the popover card, full in
      the side panel with voter attribution and the outstanding list.
- [ ] Voting is available from the popover card as well as the panel; commenting is panel-only.
- [ ] Optimistic apply → reconcile on success → visible rollback plus a toast on failure.
- [ ] Refetch and reconcile the open subject's tally on WS reconnect.
- [ ] Subscribe to `suggestion.vote.updated` and merge the broadcast tally with the local `my_vote`.

`Verify:` In the browser with two tabs signed in as different users, vote in one tab and watch
the tally update live in the other; kill the API and confirm a vote rolls back visibly with a
toast.

---

## Phase 9 — Comment thread UI

- [ ] `CommentThread` in the side panel / bottom sheet: flat, oldest first, author name with
      family colour accent, relative timestamp, "edited" marker when `edited_at` is set.
- [ ] `CommentComposer` with an `@` member picker inserting `@[Name](user:<uuid>)` markup and
      rendering it as a distinct token; character counter near the length cap.
- [ ] Edit and delete affordances driven by `can_edit` / `can_delete` from the API.
- [ ] **Delete → undo**: collapse the comment immediately and show an inline undo affordance in
      its position in the thread for ~10 seconds, not only in a toast.
- [ ] Admin deletion of another person's comment uses a confirm dialog and leaves a
      "comment removed" tombstone rather than silently reflowing.
- [ ] Live updates from `comment.created` / `.updated` / `.deleted`, reconciled by `id` so an
      undo-restore lands back in place.
- [ ] Empty state: "No comments yet — start the discussion", composer inline.
- [ ] All six field states on the composer; validate on blur, re-validate on change after the
      first error; error text beneath the field.

`Verify:` In the browser, post a comment with a mention and confirm the mentioned user's
notification bell increments; delete your own comment and undo it, confirming it returns to
its original position in the thread.

---

## Phase 10 — Admin controls and "needs my vote"

- [ ] `AdminStatusControls` at the bottom of the side panel, visually separated so it reads as
      a different kind of authority. Renders only for the main admin.
- [ ] Buttons only for transitions valid from the current status — invalid ones absent, not
      disabled-and-mysterious.
- [ ] **Reject opens a real confirm dialog** naming the suggestion and stating it will be
      hidden from the default list. Approve and shortlist commit directly (reversible).
- [ ] Handle `409` from a racing admin by re-rendering from `suggestion.status_changed`.
- [ ] "Needs my vote" count in the trip chrome from `GET /api/v1/me/pending-votes`; activating
      it applies a filter chip to the shared suggestion-list filter state and marks the
      matching pins on the map.
- [ ] Refresh the count on `suggestion.vote.updated` and `suggestion.created`.
- [ ] Zero state: "You're all caught up" — the affordance stays visible but quiet.

`Verify:` In the browser as the main admin, reject a suggestion and confirm the dialog appears
and the pin restyles for a second signed-in user without a refresh; as a member, confirm the
admin block does not render at all.

---

## Phase 11 — Web tests

- [ ] Correct control renders per mode; mismatch triggers a settings refetch.
- [ ] Optimistic vote applies, then rolls back visibly on a failed request.
- [ ] Tally widgets show the numeric value as text and render the empty state at zero votes.
- [ ] Permission-gated UI: admin controls absent for members; edit/delete affordances follow
      `can_edit` / `can_delete`.
- [ ] Undo restores a deleted comment to its original thread position.
- [ ] Reject shows a confirm dialog; approve does not.
- [ ] Mention picker inserts well-formed markup and renders it as a token.
- [ ] Playwright smoke extension: login → vote → comment → admin approve → status visible.

`Verify:` `npm test` in `web/` passes, and the Playwright smoke run completes the
login → vote → comment → confirm path against the compose stack.

---

## Phase 12 — Docs and handoff

- [ ] Re-read `requirements.md` and `design.md` against what shipped; update in the same commit
      if behaviour diverged.
- [ ] Confirm the `comments.deleted_at` PROPOSED ADDITION is reflected in
      `plan/architecture.md`'s schema section now that it is real.
- [ ] Confirm the retention cleanup task is scheduled and documented in the deploy README.
- [ ] Cross-check that `map-suggestions/design.md` still describes the status *field*
      consistently with the transitions implemented here.

`Verify:` `plan/architecture.md` lists `comments.deleted_at`, both docs in this directory match
shipped behaviour, and the cleanup task appears in the deploy README.
