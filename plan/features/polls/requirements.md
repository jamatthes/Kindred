# polls — Requirements

**Milestone:** M2. **Reads first:** `plan/overview.md`, `plan/architecture.md`,
`plan/design-system.md`, `CLAUDE.md`, `plan/features/foundation/`,
`plan/features/families/`, `plan/features/admin-console/`.

This is the feature that replaces the spreadsheet. The project began with a shared workbook in
which each family scored candidate destinations out of ten, argued about how long to go for,
and rated what they wanted to do. Polls make that structured, live and honest: everyone sees
the averages, everyone sees where the group disagrees, and everyone can see who has not voted
yet.

M2 is the milestone at which the app becomes genuinely useful to the real family group.

## The worked example

These three polls are the reference case. Every story below should be readable against them.

1. **Where shall we go?** — kind `score_matrix`. Options: York, Cornwall, Somerset, the Lake
   District, the Peak District. Each member scores every option 1–10. Cornwall and the Lake
   District both average 7.4, but Cornwall's scores cluster tightly while the Lake District
   has three 10s and three 3s — the group is split. The spread view is what makes that
   visible; the average alone hides it.
2. **How long shall we go for?** — kind `options`. Options: 5 days, 7 days, 10 days. A single
   choice per member, not a score per option.
3. **What do we want to do?** — kind `score_matrix`. Options: beaches, hiking, historic
   houses, food and drink, kid-friendly days out. Scoring these shapes what suggestions people
   later put on the map.

Poll 1's options carry coordinates, so its results tint candidate regions on the map. Polls 2
and 3 have no geometry and are table-only.

## User stories

### PL-1 — Main admin: create a score-matrix poll

**As the main admin, I can create a poll where everyone scores every option.**

- Required: title. Optional: description.
- Kind is `score_matrix`.
- I add options at creation time and can add more later while the poll is open.
- Each option has a label; I may optionally give it a location, either by picking a point on
  the map or by entering coordinates, which makes the poll's results mappable.
- I choose whether members may add their own options (`allow_member_options`).
- The poll opens immediately in `open` status.
- Example: "Where shall we go?" with York, Cornwall, Somerset, the Lake District and the Peak
  District, each pinned.

### PL-2 — Main admin: create an options poll

**As the main admin, I can create a poll where everyone picks one option.**

- Kind is `options`. Each member selects exactly one option; there is no per-option score.
- Example: "How long shall we go for?" with 5, 7 and 10 days.
- Changing my mind replaces my previous choice rather than adding a second.

### PL-3 — Member: score every option

**As a member, I can give each option a score from 1 to 10.**

- The scale is presented as 1 to 10, where 1 means "really rather not" and 10 means "yes
  please". The meaning of the ends is shown on screen, not left to guesswork.
- I can score some options and come back to the rest later; partial responses are saved and
  clearly marked as incomplete.
- I can change any score while the poll is open.
- My own scores are always distinguishable from everyone else's in the matrix.
- Scores save without a page reload and appear to other people within a second.

> NOTE: `plan/architecture.md` defines `poll_scores.score` as an integer 0–10. The interface
> collects 1–10, matching the way the family already worked in the spreadsheet; the column
> accepts 0–10 so the stored range is unchanged and a future "0 = veto" affordance needs no
> migration. Validation accepts 0–10; the UI offers 1–10.

### PL-4 — Member: vote with thumbs when that is how the poll is configured

**As a member, I give a thumbs up or thumbs down when the admin has set polls to thumbs mode.**

- The voting mode comes from `trip_category_settings` for the `poll` category, set in the
  admin console.
- In thumbs mode each option takes up, down, or no opinion.
- The results view changes to match: proportions rather than averages.
- Switching mode does not delete anything already cast; the stored votes remain and are shown
  again if the mode is switched back.

> NOTE: the mode is per category, not per poll — see the NOTE in
> `admin-console/requirements.md`, AC-5. All polls on a trip share the `poll` category's mode.

### PL-5 — Member: add an option

**As a member, I can add an option to a poll when the admin has allowed it.**

- Only when `allow_member_options` is true on that poll.
- I supply a label and, if the poll is mappable, optionally a location.
- The new option appears for everyone immediately, unscored by everyone including me.
- I can delete an option I added myself as long as nobody else has scored it.
- The admin can delete any option.
- Example: someone adds "Northumberland" to the destination poll after seeing the shortlist.

### PL-6 — Anyone on the trip: see live averages

**As a member, I can see how the group is scoring, updated as people vote.**

- Each option shows its average score to one decimal place, and the number of people who have
  scored it.
- Options are ranked by average, with the ranking updating live.
- The average is shown as a number as well as a bar — never as a bar alone.
- Bars start at zero, always.
- Where two options are within 0.2 of each other, the view says they are close rather than
  implying a decisive lead.

### PL-7 — Anyone on the trip: see where we disagree

**As a member, I can see whether a high average hides a split.**

- Each option shows the spread of individual scores: one dot per person on a 1–10 axis.
- A tight cluster and a bimodal split are visually distinct at a glance.
- A numeric measure of spread accompanies the dots, so the reading does not depend on eyesight
  alone.
- The example case must read correctly: Cornwall and the Lake District share an average of
  7.4, and the view makes plain that the Lake District splits the group.
- Titles state the finding, not the metric — "Cornwall leads; the Lake District splits the
  group", not "Average score by option".

### PL-8 — Anyone on the trip: see the whole matrix

**As a member, I can see everyone's scores for every option in one grid.**

- Rows are members, columns are options — the shape the spreadsheet had.
- Each cell shows the numeric score and is tinted on the preference ramp; the number is always
  present, so colour is never the only carrier of meaning.
- The header row and the first column stay visible while scrolling a wide or long matrix.
- Members who have not scored an option show an empty cell that is visibly different from a
  low score.
- I can sort by any option's column to see who liked what.
- Family membership is visible in the matrix, so patterns along family lines are legible.

### PL-9 — Anyone on the trip: see who has not voted

**As a member, I can see how many people still need to vote.**

- The poll shows "3 of 9 haven't voted yet".
- The names of those who have not voted are visible to everyone on the trip — this is a family
  group deciding together, not an anonymous ballot, and chasing people is the point.
- Someone who has scored some but not all options counts as partially voted and is shown
  separately from someone who has not started.
- The poll header shows completion at a glance without opening the matrix.

### PL-10 — Main admin: nudge the people who have not voted

**As the main admin, I can prompt the people who have not voted yet.**

- A single `Nudge` action sends a notification to everyone who has not completed the poll.
- The notification names the poll and deep-links to it.
- The action reports how many people were nudged.
- Nudging the same poll again is rate-limited to once every few hours, so it cannot become
  harassment.
- Anyone who has completed the poll is never nudged.

> NOTE: notifications are stored and delivered by the `notifications` feature (M6). Polls
> writes the `notifications` rows and emits the WebSocket event; if the notification centre UI
> is not yet built, the rows still exist and the bell picks them up when that feature lands.
> The nudge must not be blocked on M6.

### PL-11 — Anyone on the trip: comment on a poll

**As a member, I can discuss a poll in its comment thread.**

- Comments attach to the poll (`comments.subject_type = "poll"`).
- I can edit and delete my own comments; deleting my own is a low-stakes action and offers
  undo rather than a confirm.
- The main admin can delete any comment.
- Comment count is visible on the poll without opening the thread.
- New comments appear live.

> NOTE: the comment thread component, @mentions and their notifications belong to
> `voting-comments` (M3). Polls defines the poll as a comment subject and renders the thread;
> if M3 has not landed, polls ships a plain thread without @mention parsing, and M3 upgrades
> it in place.

### PL-12 — Main admin: close and reopen a poll

**As the main admin, I can close a poll when we have decided, and reopen it if we need to.**

- Closing sets `status = "closed"`; no further scores or options can be added.
- A closed poll stays fully visible with its results — closing is not hiding.
- Closing requires a confirm dialog naming how many people had not voted, so a poll is not
  closed out from under people by accident.
- Reopening returns it to `open` and restores voting.
- Both actions appear in the poll's history so the record is honest.

### PL-13 — Main admin: record the decision

**As the main admin, I can mark the winning option, so the poll produces an answer rather than
just numbers.**

- Marking a winner records which option won, who decided, and when.
- The winner is displayed prominently on the poll and in any list of polls.
- The winning option does not have to be the highest average — the group may decide otherwise,
  and the record reflects what was actually decided.
- The decision can be changed or cleared while the trip is not in the End stage.
- Marking a decision does not close the poll automatically; the admin is offered both actions
  together.

### PL-14 — Main admin: turn a winning option into a region on the map

**As the main admin, I can seed a map region from a winning option that has a location.**

- Offered only when the winning option has coordinates.
- Creates a `region` suggestion at that location, pre-filled with the option's label and a
  note recording which poll it came from.
- The poll option records which suggestion it created, so the link between the decision and the
  map is traceable in both directions.
- Doing this twice for the same option is prevented; the second attempt links to the existing
  suggestion instead.
- Example: Cornwall wins the destination poll and becomes the region everyone then pins
  accommodation and activities inside.

> NOTE: `suggestions` are owned by `map-suggestions` (M3). At M2 this story ships behind a
> capability check: if the suggestions table has no router yet, the button is absent. The
> column linking option to suggestion is created at M2 so the migration order is simple.

### PL-15 — Anyone on the trip: see poll results on the map

**As a member, I can see the destination poll's results as tinted areas on the map.**

- Only for polls whose options have coordinates.
- Each located option is drawn on the map, tinted by its average score using the shared
  preference ramp.
- The numeric average is always printed on the label — the tint is reinforcement, never the
  sole signal.
- Selecting an area on the map opens that option in the side panel with its spread and its
  scorers.
- The map and the table show the same numbers; there is one source of truth.
- A poll with no located options simply does not offer the map view, rather than showing an
  empty map.

### PL-16 — Anyone on the trip: find a poll

**As a member, I can see all the polls on the trip and their state.**

- A list showing title, kind, status, my completion state, the group's completion state, and
  the decided winner where one is set.
- Open polls I have not completed are surfaced first, because that is the action I need to
  take.
- Closed and decided polls stay visible for reference.

### PL-17 — Anyone on the trip: read the archive after the trip

**As a member, I can look back at how we decided, after the trip has ended.**

- In the End stage every poll is readable in full: options, matrix, averages, spread, comments
  and the recorded decision.
- Nothing can be scored, added, closed, reopened or decided.
- The frozen view is presented as a record, not as a broken form — no disabled voting controls
  cluttering the screen.

## Permissions

| Action | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| List polls, read results, matrix, spread | yes | yes | yes | no |
| See who has not voted | yes | yes | yes | no |
| Create a poll | yes | no | no | no |
| Edit a poll's title or description | yes | no | no | no |
| Delete a poll | yes | no | no | no |
| Add an option | yes | when `allow_member_options` | when `allow_member_options` | no |
| Delete an option | yes (any) | own, if unscored by others | own, if unscored by others | no |
| Cast or change my own score | yes | yes | yes | no |
| See another person's individual scores | yes | yes | yes | no |
| Change someone else's score | no | no | no | no |
| Nudge non-voters | yes | no | no | no |
| Comment | yes | yes | yes | no |
| Edit / delete own comment | yes | yes | yes | no |
| Delete another person's comment | yes | no | no | no |
| Close / reopen a poll | yes | no | no | no |
| Set or clear the decision | yes | no | no | no |
| Seed a region from a winner | yes | no | no | no |

Family admins have no elevated rights in polls. Their role governs their family's membership
and home address, not group decisions — the main admin is the one with final say per
`plan/overview.md`.

Individual scores are visible to everyone on the trip. This is a deliberate product decision:
the feature exists to replace a shared spreadsheet in which everyone could already see
everyone's numbers, and hiding them would make the disagreement view impossible.

## Stage availability

| Capability | Planning | Holiday | End |
|---|---|---|---|
| Read polls, results, matrix, spread, comments | yes | yes | yes |
| Create / edit / delete a poll | yes | yes | no (`409`) |
| Add / delete an option | yes | yes | no (`409`) |
| Cast or change a score | yes | yes | no (`409`) |
| Nudge | yes | yes | no (`409`) |
| Comment | yes | yes | no (`409`) |
| Close / reopen | yes | yes | no (`409`) |
| Set / clear a decision | yes | yes | no (`409`) |
| Seed a region from a winner | yes | yes (M3+) | no (`409`) |
| Map overlay of results | yes | yes | yes (read-only) |

Polls remain available in Holiday — `plan/overview.md` is explicit that suggestions and voting
continue during the trip, and a poll is a reasonable way to settle "what shall we do
tomorrow".

## Out of scope

- Per-poll voting-mode override. The mode is per category (PL-4).
- Anonymous or secret ballots.
- Ranked-choice, approval or weighted voting. v1 has score and thumbs only.
- Per-family voting weight. One person, one vote.
- Poll templates or duplication.
- Scheduled automatic closing.
- Exporting results to CSV or a spreadsheet.
- Multiple simultaneous decisions per poll, or partial decisions.
- Rich text or attachments in comments — that is `voting-comments` territory, and images are
  `attachments`.
- @mention parsing and mention notifications — `voting-comments` (see the NOTE on PL-11).
- Building the notification centre UI — `notifications` (see the NOTE on PL-10).
- Creating suggestions generally — `map-suggestions`. Polls only seeds one region from a
  winning option (PL-14).
- Drawing polygons for poll options. Poll options carry a point; drawn regions belong to
  `map-suggestions`.
