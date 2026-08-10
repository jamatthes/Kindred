# polls — Tasks

**Milestone M2** — the milestone at which the app replaces the family's spreadsheet. Execute in
order; each phase ends with a `Verify:` line that must pass before the next begins. Read
`requirements.md` and `design.md` in this directory first.

**Prerequisites:** `foundation`, `families` and `admin-console` complete, and the DesignSync
pass done so the token values are locked.

Throughout, use the worked example from `requirements.md` as test data: a destination
score matrix (York, Cornwall, Somerset, Lake District, Peak District), a duration options poll
(5 / 7 / 10 days), and an interests matrix (beaches, hiking, historic houses, food and drink,
kid-friendly days out).

## Phase 1 — Migration

- [ ] Alembic migration `0004_polls`:
  - [ ] `polls`: confirm `trip_id`, `title`, `description`, `kind`, `status`, `created_by`,
        `allow_member_options` exist; add `decision_option_id` (uuid null),
        `decided_by` (uuid null fk → users), `decided_at`, `closed_at`, `closed_by`
        (uuid null fk → users), `last_nudge_at`.
  - [ ] Check constraints on `polls.kind` (`score_matrix|options`) and `polls.status`
        (`open|closed`).
  - [ ] `poll_options`: confirm `poll_id`, `label`, `created_by`, `lat`, `lng`, `place_id`,
        `sort`; add `suggestion_id` (uuid null, **no FK constraint yet** — `suggestions` does
        not exist until M3; leave a comment in the migration saying M3 adds it).
  - [ ] `poll_scores`: confirm `poll_id`, `option_id`, `user_id`, `score`, `thumb`; add the
        unique constraint on `(option_id, user_id)` if absent, and a check constraint
        `score is not null or thumb is not null`, plus a check `score between 0 and 10`.
  - [ ] FK `polls.decision_option_id → poll_options.id` with `ON DELETE SET NULL`, so deleting
        a decided option clears the decision automatically.
  - [ ] Cascade deletes: poll → options → scores; poll → comments (by
        `subject_type='poll'`, handled in the service layer since `comments` is polymorphic and
        cannot carry a database FK).
  - [ ] Indexes: `poll_options(poll_id, sort)`, `poll_scores(poll_id)`,
        `comments(subject_type, subject_id)`.
- [ ] Record every PROPOSED ADDITION from `design.md` in `plan/architecture.md`'s schema
      section in the same commit.

**Verify:** `alembic upgrade head`, `downgrade -1`, `upgrade head` succeed. In psql: inserting
two `poll_scores` rows for one `(option_id, user_id)` fails; a row with both `score` and
`thumb` null fails; a `score` of 11 fails; deleting a decided option nulls
`polls.decision_option_id`.

## Phase 2 — Models

- [ ] `models/poll.py` — `Poll`, `PollOption`, `PollScore` with typed `Mapped[...]` columns and
      relationships (`Poll.options`, `PollOption.scores`).
- [ ] `models/comment.py` — the polymorphic `Comment` model, if `voting-comments` has not
      already created it. If it has, reuse it unchanged.
- [ ] A `PollStats` value object and a `compute_results(poll, scores, members, voting_mode)`
      pure function implementing every definition in the **Computed values** section of
      `design.md`: average, response count, spread (population standard deviation), the split
      flag at ≥ 2.5, the close flag at ≤ 0.2, completion states, and the thumbs counts.
- [ ] An `insight(results) -> str` function implementing the four ordered rules from
      `design.md`.

**Verify:** `pytest server/tests/test_poll_stats.py` using the worked example — build Cornwall
at `[7,8,7,8,7,8,7,8,7]` and the Lake District at `[10,10,10,3,3,3,10,3,10]`, assert both
average 7.4 to one decimal, assert Cornwall's spread is well below 2.5 and the Lake District's
is above it, and assert `insight` returns a string containing both "leads" and "splits".
Assert an option with no scores yields `average is None`, never `0.0`.

## Phase 3 — Schemas

- [ ] `schemas/poll.py` — `PollSummaryOut`, `PollOut`, `PollOptionOut`, `PollCreateIn`,
      `PollPatchIn`, `OptionCreateIn`, `OptionPatchIn`, `ScoresPutIn`, `PollResultsOut`,
      `DecisionIn`, exactly as sketched in `design.md`.
- [ ] `schemas/comment.py` — `CommentOut`, `CommentIn`.
- [ ] Validation: `score` in 0–10; `thumb` in `up|down`; exactly one of the two per entry;
      `kind` absent from `PollPatchIn` (immutable); `options` non-empty on create for
      `kind = "options"`.
- [ ] `can_delete` on `PollOptionOut` and `can_nudge` / `can_seed_region` on `PollOut` are
      computed server-side from the caller's identity and the current state — the frontend
      never derives permission.

**Verify:** `pytest server/tests/test_poll_schemas.py` — a score of 11 and a body carrying both
`score` and `thumb` are both `422`; `PollPatchIn` rejects a `kind` field.

## Phase 4 — Service layer

- [ ] `services/polls.py` holding the logic the router calls, so the rules live in one place:
  - [ ] `get_voting_mode(trip_id)` — reads the `poll` row from `trip_category_settings`.
        Never assume a mode.
  - [ ] `upsert_scores(poll, user, entries, mode)` — validates the entries against the mode
        (`422 wrong_voting_mode` on mismatch), upserts on `(option_id, user_id)`, and for
        `kind = "options"` writes the single choice as `score = 10` and deletes the user's
        other rows for that poll in the same transaction.
  - [ ] `build_results(poll, caller)` — one query for scores plus one for members, then
        `compute_results` and `insight`.
  - [ ] `close_poll` / `reopen_poll` — set `status`, `closed_at`, `closed_by`.
  - [ ] `set_decision` / `clear_decision`.
  - [ ] `nudge(poll, actor)` — finds incomplete members, writes one `notifications` row each
        with `type = "poll.nudge"` and the deep-link payload, sets `last_nudge_at`, returns the
        count. Enforces the 4-hour window.
  - [ ] `seed_region(poll, actor)` — returns the existing `suggestion_id` when already set;
        raises `not_available` when the suggestions module is absent.
- [ ] Add a module comment recording the non-obvious `options`-poll storage rule from
      `design.md` (the row's presence is the choice; the stored `10` is never displayed).

**Verify:** `pytest server/tests/test_poll_service.py` — an `options` poll where a member picks
5 days then 10 days leaves exactly one row; a thumb submitted while the mode is `score` raises
`422`; a nudge inside the window raises; a nudge with everyone complete returns 0 and writes no
notification rows.

## Phase 5 — Router

- [ ] `routers/polls.py` with every route from `design.md`.
- [ ] Every mutating route declares `Depends(require_stage("planning", "holiday"))` alongside
      its permission dependency.
- [ ] `POST /polls/{id}/options`: main admin always; others only when `allow_member_options`,
      else `403 member_options_disabled`.
- [ ] `DELETE .../options/{option_id}`: the author may delete while no other member has scored
      it (`409 option_has_scores` otherwise); the main admin may always delete, and the response
      to a confirmed admin delete cascades the scores.
- [ ] `PUT /polls/{id}/scores` writes the caller's own scores only — no `user_id` anywhere in
      the request model — and returns `PollResultsOut`.
- [ ] `POST /polls/{id}/nudge`, `PUT`/`DELETE /polls/{id}/decision`,
      `POST /polls/{id}/decision/seed-region` (returning `501 not_available` at M2).
- [ ] Comment routes scoped to the poll, plus `PATCH`/`DELETE /comments/{id}` with the author /
      main-admin rule and `edited_at` set on edit.
- [ ] Scoring a closed poll returns `409 poll_closed`.

**Verify:** in `/docs` — create the destination poll with five located options; score it as
three different users; `GET /polls/{id}/results` returns averages, spreads and a populated
`non_responders`. As a member, adding an option to a poll with `allow_member_options: false`
returns `403`. Closing the poll then scoring returns `409 poll_closed`.
`pytest server/tests/test_polls.py` — happy path, permission-denied and stage-guard for every
route.

## Phase 6 — WebSocket events

- [ ] Emit `poll.vote.updated` with the full recomputed `PollResultsOut` on every score change.
- [ ] Emit `poll.created`, `poll.updated`, `poll.deleted`, `poll.closed`, `poll.decided`,
      `poll_option.created`, `poll_option.deleted`, `comment.created`.
- [ ] Emit `notification.new` per recipient via `send_user` on nudge.
- [ ] Add the new event names to `plan/architecture.md`'s list as PROPOSED ADDITIONs.
- [ ] Consume `category_settings.updated` on the client so open polls refetch and re-render in
      the new mode.

**Verify:** `pytest server/tests/test_poll_ws.py` — a score change delivers `poll.vote.updated` to a
second connected client carrying the recomputed averages; a nudge delivers `notification.new`
only to incomplete members and not to those who have finished.

## Phase 7 — Chart widgets

Built in `web/src/charts/` per `plan/design-system.md`. Token-aware, no chart library, honesty
rules enforced by the components rather than by convention.

- [ ] `AvgBar` — ranked bars, **no `baseline` prop at all**, numeric average printed at the end
      of each bar, `insight` accepted as the title prop.
- [ ] `SpreadDots` — one row per option, one dot per member on a 1–10 axis, numeric spread
      printed alongside, overlapping dots given a count badge, split options marked with an icon
      plus the word "split".
- [ ] `HeatMatrix` — members × options; every cell prints its number and tints on
      `--scale-pref-0…10`; sticky header row and sticky first column; unscored cells rendered
      as visually distinct empties (outline or hatch), never a pale tint; the caller's own row
      marked; a family colour swatch per member row; tri-state column sort.
- [ ] `DistributionStrip` — up / down / none proportions with counts printed.
- [ ] All four render correctly in light and dark themes with no component-level colour values.
- [ ] Each accepts an `insight` title and has a documented empty state.

**Verify:** `cd web && npm test` — Vitest snapshots for each widget in both themes; a test
asserting `AvgBar` exposes no baseline prop; a test asserting every `HeatMatrix` cell contains
its numeric text (the colour-is-never-alone rule); a test asserting an unscored cell renders
differently from a cell scoring 1. Render the Cornwall / Lake District example in Storybook or
a scratch route and confirm by eye that the split is obvious.

## Phase 8 — Web: poll list and detail

- [ ] `web/src/features/polls/` — API hooks and a store subscribing to the poll events plus
      `stage.changed`, `category_settings.updated` and `member.removed`.
- [ ] Poll list table with the shared pattern; open-and-incomplete polls first with a quiet
      label explaining the order; completion as icon plus words; empty state with the create
      action inline for the main admin.
- [ ] Poll detail: map-plus-panel at 62/38 when the poll has located options, full-width table
      view when it does not.
- [ ] Panel order: header, your scores, results (`AvgBar` then `SpreadDots`), matrix
      (collapsible, expanded on desktop), comments.
- [ ] Mobile: bottom sheet at ~40% showing header and voting control above the fold; ~90% for
      the rest; the matrix collapsed by default and scrolling inside its own container so the
      page never scrolls horizontally.
- [ ] Voting controls: score mode with the ends labelled in words ("Really rather not" /
      "Yes please"), thumbs mode as a three-state control with icons and text, options mode as
      single-select. Targets ≥ 44px.
- [ ] Optimistic save with rollback and an inline message on failure; unscored options marked
      "not scored yet".
- [ ] Closed polls and the End stage render **no** voting controls at all — not disabled ones.
- [ ] Non-responder block: "3 of 9 haven't voted yet", expandable to names grouped into "not
      started" and "partly done"; the `Nudge` button for the main admin with its post-press
      count and cooldown.
- [ ] Comment thread with family colour swatches, edited markers, own-comment edit and delete
      with undo, and the main admin's delete-others behind a real confirm.
- [ ] Skeletons for list, matrix and panel; spinners for inline saves; the three empty states
      from `design.md`.
- [ ] Motion at 150–250ms on sheet and panel; bar lengths animate, the matrix does not animate
      on incoming updates; `prefers-reduced-motion` honoured.

**Verify:** in the browser with three signed-in users — create the destination poll, have all
three score it, and confirm the averages, spread and matrix update live in the other two
windows without a reload. Confirm the non-responder count is right before the third votes.
Resize to a phone width and confirm the voting control is reachable in the ~40% sheet and that
the page never scrolls sideways.

## Phase 9 — Web: map overlay

- [ ] Render located options as circular areas tinted on `--scale-pref-0…10` by average.
- [ ] Every area carries a permanent label with the option name and its numeric average.
- [ ] One shared selection model: selecting an area selects the option in the panel and scrolls
      its matrix column into view; selecting a matrix column highlights the area.
- [ ] Options with no coordinates listed beneath the map as "not on the map".
- [ ] Polls with no located options do not render the map at all.
- [ ] The tint updates live on `poll.vote.updated`.

**Verify:** in the browser — score the destination poll and watch the Cornwall area's tint and
label change in a second window. Confirm the number on the map matches the number in the
`AvgBar` and in the matrix. Add an option with no coordinates and confirm it appears in the
"not on the map" list rather than vanishing.

## Phase 10 — Decision and region seeding

- [ ] Decision dialog listing options with their averages so the admin sees the numbers while
      choosing, including when choosing against the leader.
- [ ] `Close this poll too` checkbox in the dialog.
- [ ] Persistent decision banner on the poll and in the list.
- [ ] `Create a region on the map` action on the banner, rendered only when
      `can_seed_region` is true; once used, it becomes a link to the created region.
- [ ] At M2, `can_seed_region` is false and the action is absent. Leave the wiring in place so
      M3 enables it by implementing the service call and flipping the capability check.

**Verify:** in `/docs` and the browser — set Cornwall as the decision, confirm the banner
appears in both the detail and the list, clear it and confirm it disappears. Confirm the
seed-region action is absent at M2 and that `POST .../seed-region` returns `501 not_available`.
Delete the decided option and confirm the decision clears automatically.

## Phase 11 — Admin stats and freeze regression

- [ ] Replace `admin-console`'s zero stubs for `polls_open`, `polls_closed` and `comments`
      with real trip-scoped counts.
- [ ] Add a line to `server/tests/test_admin_stage_freeze.py` for a representative mutating
      poll route, so the End-stage freeze regression covers this feature.

**Verify:** `GET /admin/stats` reports the real poll and comment counts.
`pytest server/tests/test_admin_stage_freeze.py` — with the trip in `end`, scoring, creating,
closing, deciding, nudging and commenting all return `409 stage_forbidden`, while
`POST /admin/trip/stage` still succeeds.

## Phase 12 — Tests

- [ ] `test_polls.py` — every route: happy path, permission-denied for each role that must be
      refused, stage-guard rejection.
- [ ] `test_poll_scores.py` — partial responses, changing a score, the unique constraint, the
      0–10 bounds, wrong-mode rejection, the `options`-poll single-choice rule, and last-write-
      wins on concurrent writes to one cell.
- [ ] `test_poll_stats.py` — the worked example from Phase 2, plus: no votes, one vote,
      identical votes, and an option nobody scored returning `None` rather than `0.0`.
- [ ] `test_poll_permissions.py` — a member cannot create, close, decide or nudge; a member
      cannot write another user's score by any route; a family admin has no elevated rights
      here.
- [ ] `test_poll_mode_switch.py` — scores cast in `score` mode survive a switch to `thumbs` and
      reappear on switching back.
- [ ] `test_poll_nudge.py` — recipients are exactly the incomplete members, the 4-hour window
      holds, zero-outstanding writes nothing, and rows are written even with no notification
      UI present.
- [ ] `test_poll_comments.py` — author edit sets `edited_at`, author delete, admin delete of
      another's comment, member refused deleting another's.
- [ ] Vitest: voting control per mode, optimistic rollback, the matrix's sticky header and
      first column, non-responder rendering, absence of voting controls when closed or ended,
      and the map tint matching the table value.
- [ ] Playwright smoke extension: log in → create a poll → score it → see the average update →
      decide a winner.
- [ ] Confirm no test performs a real network call.

**Verify:** `cd server && pytest` green; `cd web && npm test` green; the Playwright smoke passes
against the compose stack. Requirements PL-1 to PL-17 each map to at least one test or a
documented manual step above.

## Hand-off notes

- `poll_options.suggestion_id` is created here **without** its FK constraint. `map-suggestions`
  (M3) must add the constraint and implement `seed_region`, then flip `can_seed_region`.
- `voting-comments` (M3) upgrades this feature's comment thread in place with @mention parsing
  and mention notifications. Do not build @mentions here.
- `notifications` (M6) consumes the `poll.nudge` type and its deep-link payload. The rows are
  written from M2 onward regardless.
- The `poll` category's voting mode is read from `admin-console`; never hardcode score or
  thumbs anywhere in this feature.
- The honesty rules in the chart widgets exist to make disagreement visible. If a future
  requirement seems to need a non-zero baseline or a colour-only cell, that requirement is
  wrong — check `plan/design-system.md` before changing a widget.
