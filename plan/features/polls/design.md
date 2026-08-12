# polls — Design

**Reads first:** `plan/architecture.md`, `plan/design-system.md`,
`plan/features/foundation/`, `plan/features/admin-console/`, and `requirements.md` in this
directory.

## Data model

### `polls` (exists in `plan/architecture.md`)

`trip_id`, `title`, `description`, `kind` (`score_matrix` / `options`), `status`
(`open` / `closed`), `created_by`, `allow_member_options` (bool).

**PROPOSED ADDITION — decision columns.** Nothing in the schema records a poll's outcome, and
PL-13 requires it:

| Column | Type | Notes |
|---|---|---|
| `decision_option_id` | uuid null, fk → poll_options | the winning option; null = undecided |
| `decided_by` | uuid null, fk → users | |
| `decided_at` | timestamptz null | |

**PROPOSED ADDITION — `polls.closed_at`, `polls.closed_by`** (both nullable). PL-12 requires
the close/reopen record; `status` alone does not carry it.

**PROPOSED ADDITION — `polls.last_nudge_at`** (timestamptz null). Backs the nudge rate limit in
PL-10 without a separate table.

### `poll_options` (exists)

`poll_id`, `label`, `created_by`, `lat`/`lng` + `place_id` (nullable — geographic options
become map overlays), `sort`.

**PROPOSED ADDITION — `poll_options.suggestion_id`** (uuid null, fk → suggestions). Records
that this option was seeded into a map region (PL-14), making the link traceable in both
directions and making the "already seeded" check a column read rather than a search.

> NOTE: the FK targets `suggestions`, which does not exist until `map-suggestions` (M3). The
> column is created at M2 as a plain nullable uuid **without** the FK constraint; M3's
> migration adds the constraint. This keeps migration order simple and is recorded here so M3
> knows to complete it.

### `poll_scores` (exists)

`poll_id`, `option_id`, `user_id`, `score` (int 0–10) **or** `thumb` (`up`/`down`/null per
voting mode); unique `(option_id, user_id)`.

Both columns are nullable and exactly one is populated, according to the trip's `poll`
category voting mode at the time of casting. Storing them separately — rather than overloading
one column — is what makes PL-4's "switching mode does not delete anything" work: a score and
a thumb for the same `(option, user)` can coexist in one row, and the active mode decides
which is read.

**PROPOSED ADDITION — a check constraint** `score is not null or thumb is not null`, so an
empty row cannot be written.

For `kind = "options"` polls (PL-2), a member's single choice is stored as one `poll_scores`
row with `score = 10` on the chosen option and no rows for the others.

> NOTE: this reuses the existing table rather than adding a `poll_choices` table. The
> alternative was a new table for one narrow case. The rule is written down here because it is
> otherwise non-obvious: for `options` polls, the presence of a row **is** the choice, and the
> uniqueness of that choice is enforced in the service layer by deleting the member's other
> rows in the same transaction. The stored `10` is an implementation detail and is never shown
> as a score in the UI.

### `comments` (exists)

Polymorphic: `subject_type` (`suggestion` / `poll` / `itinerary_item`), `subject_id`,
`author_id`, `body`, `edited_at`. Polls uses `subject_type = "poll"`.

### `notifications` (exists)

`recipient_user_id`, `type`, `payload_json`, `read_at`. Polls writes rows with
`type = "poll.nudge"` and a payload deep-linking to the poll.

### `trip_category_settings` (exists, owned by `admin-console`)

Read via `GET /trip/category-settings`; the `poll` row's `voting_mode` governs every poll.

## Computed values

Defined once here so the table, the charts and the map cannot disagree.

- **Average** — the mean of non-null `score` values for an option, to one decimal place. Only
  cast scores count; a member who has not scored is excluded from the denominator, never
  treated as a zero.
- **Response count** — the number of members who have cast a score for that option.
- **Spread** — the population standard deviation of that option's scores, to one decimal
  place. Null when fewer than two people have scored.
- **Split flag** — true when spread ≥ 2.5. This is the threshold at which the Lake District
  case in the worked example reads as contested; it is a presentation hint only and is
  computed server-side so every view agrees.
- **Close flag** — set on the leading option when the second-placed average is within 0.2
  (PL-6).
- **Completion** — a member is `complete` when they have a row for every option, `partial`
  when they have at least one but not all, and `none` otherwise. For `options` polls,
  `complete` means exactly one row.
- **Thumbs mode** — `up_count`, `down_count`, `none_count` per option; no average is computed
  or displayed, because a mean of thumbs is not a meaningful number.

All of these are computed server-side in one query per poll and returned by the results
endpoint. The frontend never recomputes them.

## REST endpoints

All under `/api/v1`. Every mutating route carries
`Depends(require_stage("planning", "holiday"))` plus its permission dependency, so the End
stage freeze needs no per-route logic.

### Polls

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| GET | `/polls` | — | `[PollSummaryOut]` | `require_member` |
| POST | `/polls` | `{title, description?, kind, allow_member_options, options: [{label, lat?, lng?, place_id?}]}` | `PollOut` | `require_main_admin` |
| GET | `/polls/{id}` | — | `PollOut` | `require_member` |
| PATCH | `/polls/{id}` | `{title?, description?, allow_member_options?}` | `PollOut` | `require_main_admin` |
| DELETE | `/polls/{id}` | — | `204` | `require_main_admin` |
| POST | `/polls/{id}/close` | `{confirm: true}` | `PollOut` | `require_main_admin` |
| POST | `/polls/{id}/reopen` | — | `PollOut` | `require_main_admin` |

`kind` is immutable after creation — changing it would invalidate every stored row.

`PollSummaryOut`: `{id, title, kind, status, option_count, comment_count, my_completion: "none"|"partial"|"complete", group_completion: {complete, partial, none, total}, decision: {option_id, label}|null, created_at}`.

`PollOut` adds `description`, `allow_member_options`, `options: [PollOptionOut]`,
`voting_mode`, `closed_at`, `decided_at`, `decided_by`, `can_nudge`, `next_nudge_at`.

`PollOptionOut`: `{id, label, lat, lng, place_id, sort, created_by, suggestion_id, can_delete}`.

### Options

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| POST | `/polls/{id}/options` | `{label, lat?, lng?, place_id?}` | `PollOptionOut` | `require_member` + poll-level check |
| PATCH | `/polls/{id}/options/{option_id}` | `{label?, lat?, lng?, sort?}` | `PollOptionOut` | `require_main_admin` |
| DELETE | `/polls/{id}/options/{option_id}` | — | `204` | author if unscored by others, else `require_main_admin` |

The poll-level check on `POST`: the caller must be the main admin, **or**
`allow_member_options` must be true. Refusal is `403 member_options_disabled`.

### Scores

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| PUT | `/polls/{id}/scores` | `{scores: [{option_id, score?, thumb?}]}` | `PollResultsOut` | `require_member` |
| DELETE | `/polls/{id}/scores/{option_id}` | — | `PollResultsOut` | `require_member` (own only) |

`PUT` is a partial upsert of the caller's **own** scores only — the body has no `user_id` and
the endpoint has no way to express writing someone else's vote. It accepts one or many rows so
the UI can save a single cell or a whole row, and returns the recomputed results so the client
does not need a follow-up request.

For `kind = "options"`, the body must contain exactly one entry; the service writes it and
deletes the caller's other rows for that poll in the same transaction.

### Results

| Method | Path | Response | Permission |
|---|---|---|---|
| GET | `/polls/{id}/results` | `PollResultsOut` | `require_member` |

```
PollResultsOut = {
  poll_id, voting_mode, status,
  options: [{
    option_id, label, lat, lng,
    average: float|null, response_count: int, spread: float|null,
    is_split: bool, is_close: bool, rank: int,
    scores: [{user_id, display_name, family_id, family_color, score: int|null, thumb: str|null}],
    up_count, down_count, none_count            // thumbs mode only
  }],
  members: [{user_id, display_name, family_id, family_color, completion: "none"|"partial"|"complete"}],
  non_responders: {count, total, users: [{user_id, display_name}]},
  insight: str          // e.g. "Cornwall leads; the Lake District splits the group"
}
```

`insight` is generated server-side from the computed values, so the table, the charts and the
map all carry the same sentence. `design-system.md` requires chart titles to state the finding
rather than the metric, and generating it once is what makes that consistent. Rules, in order:
a clear leader with no split → "X leads"; a leader within 0.2 of the runner-up → "X and Y are
neck and neck"; any option with `is_split` → append "; Z splits the group"; nobody has voted →
"No scores yet".

### Nudge

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| POST | `/polls/{id}/nudge` | — | `{nudged: int, next_nudge_at}` | `require_main_admin` |

Writes one `notifications` row per incomplete member with
`type = "poll.nudge"` and `payload_json = {poll_id, poll_title, deep_link: "/polls/<id>"}`,
sets `last_nudge_at`, and emits `notification.new` to each recipient. Rate-limited to once per
4 hours per poll; a second attempt returns `429 nudge_too_soon` with `next_nudge_at`.

### Decision

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| PUT | `/polls/{id}/decision` | `{option_id}` | `PollOut` | `require_main_admin` |
| DELETE | `/polls/{id}/decision` | — | `PollOut` | `require_main_admin` |
| POST | `/polls/{id}/decision/seed-region` | — | `{suggestion_id}` | `require_main_admin` |

> NOTE (implementation): `design.md`'s permission column throughout this section says
> `require_main_admin`. That dependency was renamed **`require_organiser`** when the role
> hierarchy was revised (`plan/overview.md` > Roles, 2026-08-11): the trip's owner, or an
> organiser they appointed. Family heads and spouses have no elevated rights in polls.

`seed-region` requires a decided option with coordinates. It creates a `region` suggestion at
that point with the option's label as the title and a note recording the poll it came from,
then writes `poll_options.suggestion_id`. If that column is already set, it returns the
existing `suggestion_id` with `200` rather than creating a duplicate.

At M2 the route returns `501 not_available` when the suggestions router is absent, and
`PollOut.can_seed_region` reads false so the button is not rendered.

### Comments

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| GET | `/polls/{id}/comments` | — | `[CommentOut]` | `require_member` |
| POST | `/polls/{id}/comments` | `{body}` | `CommentOut` | `require_member` |
| PATCH | `/comments/{id}` | `{body}` | `CommentOut` | author only |
| DELETE | `/comments/{id}` | — | `204` | author, or `require_main_admin` |

Written against the polymorphic `comments` table with `subject_type = "poll"`. `PATCH` sets
`edited_at`, and the UI shows an "edited" marker — an edit that leaves no trace would falsify
the discussion record.

## WebSocket events

Emitted, all to the trip room unless noted:

| Event | When | Payload | Consumers |
|---|---|---|---|
| `poll.vote.updated` | any score or thumb changes | `{poll_id, results: PollResultsOut}` | matrix, charts, map tint, completion counts |
| `poll.created` | a poll is created | `{poll: PollSummaryOut}` | poll list |
| `poll.updated` | title, description or `allow_member_options` changes | `{poll: PollSummaryOut}` | poll list, poll header |
| `poll.deleted` | a poll is deleted | `{poll_id}` | poll list |
| `poll.closed` | closed or reopened | `{poll_id, status, closed_at}` | poll list, poll header, voting controls |
| `poll.decided` | decision set or cleared | `{poll_id, decision}` | poll list, poll header, map |
| `poll_option.created` | an option is added | `{poll_id, option: PollOptionOut}` | matrix columns, map |
| `poll_option.deleted` | an option is removed | `{poll_id, option_id}` | matrix columns, map |
| `comment.created` | a comment is posted | `{subject_type, subject_id, comment: CommentOut}` | comment thread, count |
| `notification.new` | a nudge is sent | `{notification}` — sent per recipient via `send_user` | notification bell |

`poll.vote.updated` and `notification.new` are the reserved names from `plan/architecture.md`. The
remainder are **PROPOSED ADDITION**s to that list.

`poll.vote.updated` carries the full recomputed `PollResultsOut` rather than a delta. Recomputation
is a single cheap query at this scale, and shipping the whole object removes any possibility
of the matrix, the charts and the map drifting apart from partially applied deltas.

Consumed:

- `stage.changed` — on `end`, voting controls are removed and the archive presentation is used
  (PL-17).
- `category_settings.updated` — when the `poll` category's mode changes, open poll views
  refetch and re-render as score or thumbs.
- `member.removed` — the removed member's column disappears from the matrix and the completion
  counts drop; their existing scores remain in the database.

## UI behaviour

Per `plan/design-system.md`. This is the feature that most needs its honesty rules: the whole
point is to show disagreement rather than paper over it with an average.

### Poll list

Reached from the nav rail. A table using the shared pattern — tri-state sort, sticky header,
full-row click target, tabular right-aligned numerics. Columns: title, kind, status, my
completion, group completion, decision.

Ordering puts open polls I have not completed first (PL-16), with a quiet label explaining the
ordering so it does not look arbitrary. My completion renders as an icon plus words
("Not started", "3 of 5", "Done") — never a bare colour dot.

Empty state: "No polls yet — the first one usually decides where to go" with the create action
inline for the main admin, and an explanatory line for everyone else.

### Poll detail — desktop

The standard layout: map centre (~62%) with the right side panel (~38%) **when the poll has
located options**. When it does not, the poll takes the full content width as a table view,
because an empty map would be noise (PL-15).

> NOTE (implementation, Phase 8): shipped as a **poll-list column beside a detail column**,
> following the agreed mockup `design-preview/screen-polls.html`, not the map-plus-panel
> above. `plan/overview.md`'s UI-first rule says feature UI starts from the agreed mockup, and
> the mockup is right: a poll's centre of gravity is the matrix, which is wide, and giving it
> 62% of the width while a map beside it shows five circles is the wrong trade. The mockup
> also has no map on this screen at all. What survived from this paragraph is the rule that
> mattered — a poll with no located options must not render an empty map — which is now true
> trivially.
>
> **The map overlay (PL-15, Phase 9) is not built.** There is no configured
> `GOOGLE_MAPS_BROWSER_KEY` in this environment and no map component in the app yet; the
> browser SDK arrives with `map-suggestions` (M3). The **data** side is complete: options
> store `lat`/`lng`/`place_id`, `PollResultsOut.options` carries the coordinates and the
> average, and the tint value is the shared `--scale-pref-N` ramp — so the overlay is a
> rendering job over an API that already answers it. `map-suggestions` picks this up; see the
> hand-off notes.

Panel contents, top to bottom:

1. **Header** — title, description, status chip, completion summary ("3 of 9 haven't voted
   yet"), and the decision banner when one is set.
2. **Your scores** — the voting control (below).
3. **Results** — `AvgBar` then `SpreadDots`.
4. **Matrix** — `HeatMatrix`, collapsible, expanded by default on desktop.
5. **Comments** — the thread.

### Poll detail — mobile

Full-bleed map with the poll as a bottom sheet at the ~40% snap showing the header and the
voting control — the action the member came to take is above the fold and within thumb reach.
Raising to ~90% reveals results, matrix and comments. The matrix is collapsed by default on
mobile and scrolls horizontally within its own container; the page itself never scrolls
sideways.

### Voting control

**Score mode.** One row per option, each with a 1–10 control. The ends are labelled in words
("Really rather not" at 1, "Yes please" at 10) per PL-3 — the numbers alone do not say which
direction is good. The current value is shown numerically beside the control. Targets ≥ 44px
on touch.

Saving is optimistic: the cell updates immediately, `PUT /polls/{id}/scores` fires, and a
failure or a WebSocket error rolls the value back with an inline message. Unscored options
carry a quiet "not scored yet" marker so a partial response is visibly partial.

**Thumbs mode.** Up / down / no opinion per option as a three-state control with icons and
text labels.

**Options-poll mode.** A single-select list; choosing a different option replaces the previous
choice with no extra interaction (PL-2).

**Closed or End stage.** The control is not rendered at all. Disabled controls are not left on
screen — PL-17 asks for a record, not a broken form.

### Charts

From `web/src/charts/`, per `design-system.md`. No chart library is added.

- **`AvgBar`** — one bar per option, ranked, zero-baselined (the component has no `baseline`
  prop), with the numeric average printed at the end of every bar. The `insight` string from
  the API is passed as the `insight` title prop.
- **`SpreadDots`** — one row per option, one dot per member on a 1–10 axis, with the numeric
  spread printed alongside. Split options are marked with an icon plus the word "split", never
  colour alone. This is the widget that carries PL-7, and the Lake District case is its
  acceptance test.
- **`HeatMatrix`** — members × options. Each cell prints the number and tints it on
  `--scale-pref-0…10`. Sticky header row and sticky first column. Unscored cells are visually
  distinct from low scores — a hatched or outlined empty cell, not a pale tint that reads as a
  1. The member's own row is marked. Family colour appears as a small swatch on each member
  row, so patterns along family lines are legible (PL-8). Columns sort tri-state.
- **`DistributionStrip`** — thumbs mode only: up / down / none proportions per option with
  counts printed.

The preference ramp is the shared token set, so a score of 8 is the same colour in the matrix
cell, the spread dot and the map tint (PL-15).

### Non-responders and nudge

Beneath the header: "3 of 9 haven't voted yet", expandable to the names, grouped into "not
started" and "partly done" (PL-9). For the main admin, a `Nudge` button sits alongside; after
a press it reports how many were nudged and disables with the time until it is available
again. The names are visible to everyone — deliberately, per the permissions note.

### Map overlay

Located options render as circular areas centred on their coordinates, tinted by average score
on the preference ramp. Every area carries a permanent label with the option name and its
numeric average — the tint never carries the value alone (PL-15).

Selecting an area selects that option in the panel and scrolls its row into view in the matrix.
Selecting a matrix column highlights the corresponding area. One selection model shared by both
views.

Options with no coordinates are listed beneath the map as "not on the map", so they are not
silently dropped from a poll that is otherwise mapped.

### Decision

Setting a decision opens a small dialog listing the options with their averages, so the admin
sees the numbers while choosing — including when they are deliberately choosing against the
leader (PL-13). Confirming records it and shows a persistent banner on the poll ("Decided:
Cornwall"). The dialog offers `Close this poll too` as a checkbox, since the two usually happen
together but do not always.

When the winning option has coordinates and the suggestions feature is available, the banner
carries a `Create a region on the map` action (PL-14). Once used, it becomes a link to the
created region.

### Comments

Standard thread: author with family colour swatch, timestamp, body, edited marker. Own
comments carry edit and delete; delete uses undo rather than a confirm, per
`design-system.md`'s "undo over confirm for low-stakes destructive actions". The main admin's
delete of someone else's comment is a real confirm, because it is not their content.

### Close and reopen

`Close` opens a confirm naming the count: "4 of 9 people haven't voted. Close anyway?" (PL-12).
`Reopen` is a plain action with no confirm — it restores capability rather than removing it.

### Loading and empty states

Skeletons for the poll list, the matrix and the panel structure; spinners only for the
sub-second inline save. Empty states: no polls; a poll with no options yet ("No options yet —
add the first"); a poll where nobody has scored ("No scores yet — be the first"), with the
charts absent rather than rendered empty.

### Motion

150–250ms on sheet-up, panel-in and the decision banner. Score changes animate the bar length
only; the matrix does not animate on every incoming `poll.vote.updated`, because a live-updating
grid that moves constantly is unreadable. `prefers-reduced-motion` drops all of it.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| Nobody has voted | `average`, `spread` null; `insight` is "No scores yet"; charts are not rendered and the empty state shows |
| One person has voted | Average shown; `spread` null; `SpreadDots` shows the single dot with a note that spread needs at least two responses |
| Everyone scored an option identically | `spread` 0.0; not flagged as split; the dots overlap and are drawn with a count badge |
| An option nobody scored | Shown with a null average and "not scored yet", never as 0.0 — a zero would be a fabricated data point |
| Option deleted after scores exist | Only the main admin can do it; a confirm names how many scores will be lost; the scores are deleted with the option (cascade) |
| Member deletes their own option after someone else scored it | `409 option_has_scores` |
| Member adds an option while others are mid-vote | `poll_option.created` inserts the column live; existing scores are untouched; the new column reads "not scored yet" for everyone |
| Scoring a closed poll | `409 poll_closed` |
| Scoring in the End stage | `409 stage_forbidden` |
| Score outside 0–10 | `422 validation_error` |
| A thumb sent while the mode is `score` (or the reverse) | `422 wrong_voting_mode`, naming the current mode |
| Voting mode switched mid-poll | Stored rows are kept; the results endpoint reads the column matching the current mode; options with no value in that mode read as unvoted. `category_settings.updated` makes open clients refetch |
| `options` poll receives multiple entries in one `PUT` | `422 single_choice_required` |
| Two devices score the same cell at once | Last write wins on the unique `(option_id, user_id)` row; both receive `poll.vote.updated` and converge |
| Optimistic update contradicted by the broadcast | The server value wins and the cell corrects itself; a brief inline note appears if it differs from what the user set |
| Nudge with nobody outstanding | `200` with `nudged: 0` and a message saying everyone has voted; no notifications written |
| Nudge inside the 4-hour window | `429 nudge_too_soon` with `next_nudge_at` |
| Nudge when `notifications` UI is unbuilt | Rows are still written and the event still emitted; nothing fails |
| Decision set to an option that is later deleted | The delete clears `decision_option_id` in the same transaction and the banner disappears |
| Decision on an option with no coordinates | Allowed; the seed-region action is simply not offered |
| `seed-region` before `map-suggestions` exists | `501 not_available`; `can_seed_region` is false so the button was never shown |
| `seed-region` pressed twice | Returns the existing `suggestion_id` with `200`; no duplicate is created |
| Poll deleted with comments and scores | Main admin only, real confirm naming both counts; cascade delete |
| Matrix with many members and options | The matrix scrolls inside its own container with sticky header and first column; the page never scrolls horizontally |
| Member removed from the trip mid-poll | Their column disappears and completion counts drop; their scores stay in the database and reappear if they are re-invited |
| Poll list opened in the End stage | Full read access; no create, close, decide or vote controls anywhere |
| `poll.vote.updated` arrives for a poll not open on screen | The list's completion counts update; no other work is done |
| WebSocket disconnected while voting | The optimistic value stays, the `PUT` still goes over REST, and the client refetches results on reconnect (`resync`) |

## Dependencies and hand-offs

- **Depends on `foundation`** for auth, `require_member` / `require_main_admin` /
  `require_stage`, the error envelope and the WebSocket helpers.
- **Depends on `families`** for the family colour slot shown on member rows in the matrix.
- **Depends on `admin-console`** for `GET /trip/category-settings`, which decides score versus
  thumbs. Never assume a mode.
- **Depends on `design-system`** for `HeatMatrix`, `AvgBar`, `SpreadDots`,
  `DistributionStrip` and `--scale-pref-0…10`. If a widget does not yet exist, build it in
  `web/src/charts/` under that feature's rules — do not add a chart library, and do not work
  around the honesty rules.
- **Provides to `notifications`** the `poll.nudge` notification type and its deep-link payload.
- **Provides to `voting-comments`** a working poll comment thread to upgrade in place with
  @mentions.
- **Provides to `map-suggestions`** the seeded region from a winning option, and the
  `poll_options.suggestion_id` link that must gain its FK constraint in M3's migration.
- **Provides to `admin-console`** the real `polls_open` / `polls_closed` and `comments` counts,
  replacing the zero stubs in its stats section.
