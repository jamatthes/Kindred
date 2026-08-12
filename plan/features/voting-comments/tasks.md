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

- [x] **Already done — no new chart code required.** `AvgBar`/`DistributionStrip`/
      `SpreadDots` (`web/src/charts/`) shipped generic during the M2 chart-typography
      rework (see `design-system.md`'s 2026-08-12 NOTE): `AvgBar` takes any
      `{label, value, count}[]`, `SpreadDots` any `{label, scores}[]`, `DistributionStrip`
      any `up`/`down`/`none` — none of them are poll-specific. Every box below was already
      true of the existing implementation; this feature only had to call them with a
      suggestion's tally instead of a poll's:
      - [x] Bars start at zero, no `baseline` prop.
      - [x] `DistributionStrip` shows up/down/**none** as three visible proportions.
      - [x] `SpreadDots` — one dot per member, 0–10 axis.
      - [x] Token-aware throughout; `--scale-pref-0…10` ramp used by `AvgBar`'s emphasis
            and (via `map-suggestions/prefTint.ts`) the same ramp region tints use.
      - [x] Numeric value always rendered as text (HTML, not SVG — the chart-typography
            rework's own rule).
      - [x] Empty state at `count: 0` (`ChartEmptyState`, `web/src/charts/a11y.tsx`).
      - [x] Reduced motion: no widget in this library animates its bars in the first place
            (the chart-typography NOTE moved all motion decisions to plain CSS transitions
            on HTML elements outside the SVG) — the one new animated element this feature
            adds, `VoteTally`'s compact list-row bar, has its own
            `@media (prefers-reduced-motion: reduce)` rule in `voting-comments/voting.css`.

`Verify:` The pre-existing chart test suites (`AvgBar.test.tsx`, `DistributionStrip.test.tsx`,
`SpreadDots.test.tsx`) already cover every box above generically. This feature adds
`SuggestionVotePanel.test.tsx`'s own empty-state/numeric-as-text assertions on top, using a
suggestion tally rather than poll data, so the honesty rules are proven against this
feature's actual call sites too, not only the generic widget tests.

---

## Phase 8 — Vote UI

- [x] `web/src/features/voting-comments/api.ts` (votes + comments REST client) and `store.ts`
      — **deviation**: no separate store file. The one piece of shared state this feature
      needed (`needsMyVote`) was added directly to `map-suggestions/store.ts`'s existing
      `SuggestionFilters`, per the coordinator's own framing ("wired into the shared
      suggestion filter store you built") — a second store object for one boolean would
      have split "what's selected/filtered" across two sources of truth, exactly what that
      store's docblock says the design avoids. Everything else voting-specific is hook
      state (`useVotes.ts`, `useComments.ts`), not global.
- [x] `ScoreVoteControl.tsx`: 0–10 `radiogroup`, each step tinted with `--scale-pref-N`,
      digit shown on the button and the chosen value repeated as text beside the control,
      roving-tabIndex arrow-key navigation (Enter/Space commit via native button
      semantics), `--hit-target` sizing (`--vote-step-compact` at the compact density).
- [x] `ThumbsVoteControl.tsx`: icon + word on both buttons, distinct `is-on` state, a
      "Clear" affordance that only renders once a vote exists.
- [x] `useCategoryMode.ts` resolves mode from `trip_category_settings` by the suggestion's
      `type` — reusing `polls/api.ts`'s `categoryApi` rather than a second client for the
      same read (see the deviation note in `design.md`); refetches on any vote failure,
      which covers the `422` mismatch case `design.md` calls out.
- [x] `VoteTally.tsx`: compact (plain number+bar, list row), medium and full (real
      `AvgBar`/`DistributionStrip`/`SpreadDots` + `VoterAttribution`, `SuggestionVotePanel`
      wires density straight through). `CompactVoteTally` reads the list response's own
      `vote_summary` rather than firing a tally request per row (N+1 avoidance, noted
      inline in `VoteTally.tsx`).
- [x] Voting from the popover card: `MapSuggestionsScreen`'s mobile `PopoverCard` renders a
      `SuggestionVotePanel` at `density="medium"` in its `voteSummary` slot. **Deviation**:
      on desktop there is no standalone popover at all (documented in `map-suggestions`'
      own deviation note) — voting is still available without leaving the map view, through
      the side panel that opens beside it, just not through a separately-anchored card.
- [x] Optimistic apply → reconcile → visible rollback (`useVotes.ts`, pure math in
      `voteMath.ts`) → toast on failure (`SuggestionVotePanel.tsx`, fired once per new
      error via a ref guard so a persisted error state does not re-toast on every render).
- [x] `resync` refetches and reconciles the open subject's tally (`useVotes.ts`).
- [x] `suggestion.vote.updated` merged with the locally-known `my_vote` — the broadcast
      payload's absence of that field never overwrites it.

`Verify:` `useVotes.test.tsx` proves the optimistic-apply/rollback cycle and the WS merge
directly against a mocked API+socket. The two-tab live-update and kill-the-API browser
checks are deferred to integration — no backend exists in this worktree (see Phase 12).

---

## Phase 9 — Comment thread UI

- [x] `CommentThread.tsx`: flat, oldest first, author + family colour (`IdentityBadge`),
      relative timestamp, "edited" marker. **Deviation, recorded and reasoned in
      `design.md`**: a new polymorphic component rather than upgrading
      `polls/CommentThread.tsx` in place, which that file's own docblock predicted this
      feature would do — retrofitting a different, already-shipped feature's component
      mid-build risked regressing poll comments for a change outside this phase's scope.
- [x] `CommentComposer.tsx` with an `@` picker (`mentions.ts` — `activeMentionQuery`/
      `insertMention`) inserting well-formed `@[Name](user:<uuid>)` markup, rendered back
      as a `.comment__mention` token by `splitMentions`; character counter appears once
      the body nears the 4000-char cap.
- [x] Edit/delete driven by `can_edit`/`can_delete` from the `Comment` type — never
      re-derived client-side.
- [x] Delete → undo: `useComments.ts`'s `removals` overlay keeps the comment in the array
      (never splices it), rendering an inline "Undo" row in place for `UNDO_WINDOW_MS`
      (10s) — this is what makes "restores to its original position" true for free, proven
      in `CommentThread.test.tsx`.
- [x] Admin deletion of someone else's comment: `ConfirmDialog`, then a permanent
      "Comment removed." tombstone in place, no undo shown.
- [x] Live `comment.created`/`.updated`/`.deleted` reconciled by `id`; an undo-restore
      (`comment.created` per `design.md`) clears the removal overlay and lands the comment
      back in its existing array position.
- [x] Empty state exact wording, composer inline.
- [x] Composer field states via the same `TextField`/error-beneath-field convention every
      other form in the app uses (validate-on-blur, re-validate-after-first-error).

`Verify:` `CommentThread.test.tsx` covers the empty state, mention-token rendering, own
delete → undo → restore-to-position, moderation delete → confirm → tombstone, and
permission-gated edit/delete. The bell-increment and cross-tab browser checks are deferred
to integration (no backend, no `notifications` feature yet).

---

## Phase 10 — Admin controls and "needs my vote"

- [x] `AdminStatusControls.tsx` — visually separated block (`.admin-status`, a bordered
      sunken panel), renders for `is_owner || is_organiser` (this codebase's post-2026-08-11
      role vocabulary; "main admin" in `requirements.md`/`design.md` predates the
      owner/organiser split and maps onto this pair — same gate `map-suggestions` already
      used before this phase). Replaces the inline status buttons
      `map-suggestions/SuggestionDetailPanel.tsx` had as a Phase-8 placeholder.
- [x] Only valid-from-current-status buttons render (`TRANSITIONS` map, one entry per
      status) — absent, not disabled.
- [x] Reject opens `ConfirmDialog` naming the suggestion and the hidden-from-list
      consequence; Approve/Shortlist/Reopen call `suggestionsApi.setStatus` directly.
- [x] A `409` shows "Someone else already changed this suggestion's status" rather than
      retrying; the corrected status arrives through the existing prop chain
      (`useSuggestionList`'s own `suggestion.status_changed` subscription one level up
      feeds `MapSuggestionsScreen`'s `selected`, which is `AdminStatusControls`' own
      `suggestion` prop) — no second subscription needed in this component.
- [x] `usePendingVotes.ts` + `PendingVotesChip.tsx`: the count, refreshed on
      `suggestion.vote.updated`/`suggestion.created`/`resync`. Activating it calls
      `suggestionStore.toggleNeedsMyVote()` (the new field on `map-suggestions/store.ts`'s
      `SuggestionFilters`). **Deviation**: "marks the matching pins on the map" is achieved
      by filtering — `MapSuggestionsScreen` intersects the fetched suggestion list with
      `pending-votes`' id set client-side (there is no server list param for it, per
      `design.md`'s own REST contract), so only the matching pins render at all rather than
      the full set with the matching ones highlighted. The net visual effect ("which pins
      need my vote") is the same; a highlight-without-hiding variant is a smaller follow-up
      if the group finds pure filtering too aggressive in practice.
- [x] Zero state: "You're all caught up", chip stays visible and clickable (toggles off an
      already-inactive filter harmlessly).

`Verify:` `AdminStatusControls.test.tsx` covers the transition matrix, the reject-confirms/
approve-commits-directly split, absence for non-admins, and the 409 message.
`PendingVotesChip.test.tsx` covers the count, the zero state, and the toggle. The two-user
browser check (reject in one session, restyle in another) is deferred to integration.

---

## Phase 11 — Web tests

- [x] `SuggestionVotePanel.test.tsx`: score control renders for score mode, thumbs for
      thumbs mode, never the wrong one; read-only surfaces render no control at all.
- [x] `useVotes.test.tsx`: optimistic apply is visible before the request resolves,
      reconciles on success, and rolls back to the exact previous tally on failure.
- [x] `SuggestionVotePanel.test.tsx` + `voteMath.test.ts`: numeric values render as text,
      a zero-vote tally renders the empty state, and a cleared last vote produces `null`
      (never a fabricated `0.0`) — the honesty rule asserted at the actual optimistic-math
      layer, not only at the generic chart-widget layer.
- [x] `AdminStatusControls.test.tsx` + `SuggestionDetailPanel.test.tsx` (map-suggestions):
      admin block absent for members, present and transition-correct for organisers;
      `CommentThread.test.tsx`: edit/delete follow `can_edit`/`can_delete` exactly.
- [x] `CommentThread.test.tsx`: undo restores a comment to its original array position
      (asserted via row order, not just re-appearance).
- [x] `AdminStatusControls.test.tsx`: Reject opens `alertdialog` and fires no request until
      confirmed; Approve/Shortlist fire immediately with no dialog.
- [x] `mentions.test.ts` (pure insertion/parsing) + `CommentThread.test.tsx` (rendered
      token, not raw markup, in a real thread).
- [ ] **Playwright smoke extension — explicitly skipped**, same reasoning as
      `map-suggestions`'s Phase 11: needs the real backend (login → vote → comment → admin
      approve), which does not exist in this worktree. Deferred to integration.

`Verify:` `npm test` (`vitest run`) in `web/`: 418 passing / 4 failing, all 4 pre-existing
and unrelated (`app/ui/pickers/DatePicker.test.tsx`/`DateRangePicker.test.tsx`, predating
this branch). `npm run build` and `npm run check:tokens` both pass. The Playwright leg does
not run — see the skipped box above.

---

## Phase 12 — Docs and handoff

- [x] Re-read both docs against what shipped; deviations recorded in the dated NOTE at the
      bottom of `design.md` (this web pass only — the server-side Phases 1–6 are a separate
      agent's work and are not re-verified here).
- [x] `comments.deleted_at` confirmed already present in `plan/architecture.md` (~line 139)
      — no change needed, checked rather than assumed.
- [ ] **Retention cleanup task / deploy README entry — not this phase's work.** Server-side
      maintenance task (Phase 5), out of scope for a web-only implementer; left for whoever
      builds `server/`.
- [x] Cross-checked: `map-suggestions/design.md` still describes `status` as a field this
      feature transitions, not something it stores independently — `AdminStatusControls`
      calls `map-suggestions/api.ts`'s `suggestionsApi.setStatus`, the same endpoint
      `map-suggestions`'s own docs own, so there is exactly one status-write path.

`Verify:` `plan/architecture.md` lists `comments.deleted_at` (confirmed). Both docs in this
directory carry a dated NOTE matching shipped web behaviour. The cleanup task's deploy-README
entry remains the backend implementer's to add.
