# admin-console — Requirements

**Milestone:** M1. **Reads first:** `plan/overview.md`, `plan/architecture.md`,
`plan/design-system.md`, `CLAUDE.md`, `plan/features/foundation/`,
`plan/features/families/`.

One page, visible only to the main admin, holding everything that configures the trip and the
instance: trip details, the stage machine, voting modes per category, an overview of every
family and member with account-level actions, instance settings, the Google API key status,
and platform statistics.

This is the only place the trip's stage can change, so it is the feature that makes the End
stage's read-only freeze real.

## User stories

### AC-0 — Main admin: set up the trip on first login

**As the seeded main admin, after changing my password I am guided through setting up the trip.**

- After a successful password change (`foundation` F-5), I am redirected to a dedicated trip
  setup screen instead of the app home — a single-purpose, fullscreen form outside the app shell.
- The screen explains: "Set up your trip — configure destinations and invite families next."
- I fill in: trip name (required), start date (optional during Planning), end date (optional
  during Planning), timezone (required, defaults to container's `TZ`).
- The timezone field offers a searchable dropdown of IANA zones; the default is the container's
  `TZ` env var.
- On submit, the trip is updated with these values, and I land on the app home. The trip name
  is immediately visible in the top bar.
- If I navigate away or close without saving, on next login I return to this setup screen until
  the trip name and timezone are set.
- This screen is not shown for users who did not require a password change (i.e., anyone not
  the seeded admin).

### AC-1 — Main admin: reach the console

**As the main admin, I can open an admin page that nobody else can see.**

- The nav rail (desktop) and the tab bar (mobile) show an `Admin` entry only for the main
  admin.
- A non-admin who navigates directly to the URL sees a "you do not have access" screen, and
  every underlying endpoint returns `403` regardless of what the frontend shows.
- The page is organised into labelled sections rather than tabs-within-tabs, so everything is
  scannable in one pass.

### AC-2 — Main admin: edit trip settings

**As the main admin, I can set the trip's name, dates and timezone.**

- Editable: `name`, `start_date`, `end_date`, `timezone`.
- Dates may be empty while the trip is in Planning (the destination is not decided yet) and
  are required before moving to Holiday.
- `end_date` must not be before `start_date`.
- Timezone is chosen from the IANA list; the default comes from the container's `TZ`.
- The trip name appears in the app header and on the invite preview, so a change is visible
  everywhere immediately.
- Changes are saved explicitly with a `Save` action, not on blur — these are consequential
  values.

### AC-3 — Main admin: move the trip to the next stage

**As the main admin, I can advance the trip from Planning to Holiday, and from Holiday to End.**

- The current stage is displayed prominently with a one-line description of what it means.
- Only forward transitions are offered: Planning → Holiday → End.
- Each transition requires a confirm dialog that states, in plain words, what will change.
- Planning → Holiday requires `start_date` and `end_date` to be set; if they are not, the
  action is disabled with the reason shown.
- Holiday → End warns that the trip becomes permanently read-only for everyone.
- After a transition every connected client updates without a reload: mutating controls
  appear or disappear according to the new stage.
- The transition is recorded with who did it and when.

### AC-4 — Main admin: undo a stage change I just made by mistake

**As the main admin, I can move the trip back a stage if I advanced it in error.**

- Backward transitions (Holiday → Planning, End → Holiday) are available to the main admin
  only, behind a separate, more emphatic confirm that names the action as a correction.
- Going back from End is the only mutation permitted while in End; everything else stays
  frozen.
- The trip's stage history records the reversal too, so the record is honest.

> NOTE: `plan/overview.md` describes End as "everything frozen read-only", and
> `plan/architecture.md` says "End stage rejects all mutations except admin stage-change".
> Reversal is therefore in scope precisely because the architecture document carves out the
> stage change itself. It is presented as a correction, not as a normal part of the lifecycle.

### AC-5 — Main admin: choose how each category is voted on

**As the main admin, I can set whether each category is scored 1–10 or voted with thumbs.**

- The five categories from `trip_category_settings` are listed: `poll`, `region`,
  `accommodation`, `activity`, `meal`.
- Each has a voting mode of `score` or `thumbs`.
- Each row explains the effect in one line ("Members give each option a score from 1 to 10" /
  "Members give a thumbs up or thumbs down").
- Defaults are seeded for all five categories when the trip is created, so nothing is ever
  unset.
- Changing a mode when votes already exist shows a warning first, explaining that existing
  votes in that category stay stored but will not be shown in the new mode until re-cast.
- Changes take effect for every connected client immediately.

> NOTE: `plan/overview.md`'s decision log says voting mode is configurable "per poll / per
> suggestion category", while the `trip_category_settings` table in `plan/architecture.md` is
> keyed by `(trip_id, category)` with `poll` as one of the five categories. The schema wins:
> the mode is set per category, and all polls share the `poll` category's mode. Per-poll
> override is out of scope for v1 and would need a new column.

### AC-6 — Main admin: see every family and member in one place

**As the main admin, I can see the whole membership of the trip on one screen.**

- A table of families: colour, name, member count, home status.
- A table of members: display name, username, family, role, whether they have ever logged in,
  and whether they are currently required to change their password.
- Both tables sort and can be filtered by a single search box.
- From here I can jump to the family's detail panel in the `families` feature rather than
  duplicating its editing UI.

### AC-7 — Main admin: reset someone's password

**As the main admin, I can reset a member's password when they are locked out.**

- The action generates a temporary password, shown once with a copy action, and sets that
  user's `must_change_password` flag.
- All of that user's existing sessions are revoked immediately, so a stolen session cannot
  survive the reset.
- On their next login they are forced through foundation's change-password screen.
- A confirm dialog precedes the reset because it invalidates the person's access.
- I cannot reset my own password this way; the profile page is the route for that.
- There is no email delivery — the temporary password is handed over by whatever channel the
  family already uses.

### AC-8 — Main admin: remove a person from the trip

**As the main admin, I can remove someone entirely.**

- The action removes their family membership and revokes their sessions, so they lose access
  immediately.
- Their contributions — votes, comments, suggestions, poll scores, check-ins — are retained
  and stay attributed to their display name, so the record of how decisions were made is not
  falsified.
- A confirm dialog states plainly that content is kept and access is removed.
- I cannot remove myself.
- Removing the last admin of a family is refused with an explanation, matching the rule in
  `families`.

### AC-9 — Main admin: configure the instance

**As the main admin, I can set instance-level settings that are not specific to one trip.**

- `instance_name` — shown on the login screen and the invite preview.
- Registration policy — displayed as the current policy with `invite-only` as the only
  selectable value in v1; other options are shown as unavailable with a short note, rather
  than hidden, so the intent is visible.
- Settings are stored in the `settings` key/value table.

### AC-10 — Main admin: check whether the Google APIs are working

**As the main admin, I can check which Google APIs are responding, so I can tell whether a
missing map or distance is a configuration problem.**

- A section lists the APIs the product uses: Maps JS, Places, Geocoding, Distance Matrix,
  Directions.
- Each shows whether a key is configured and the result of the last check: `ok`, `denied`
  (key rejected or API not enabled), `quota`, `unreachable`, or `never checked`.
- The check runs **only when I press `Run check`** — never on page load, and never on any
  render path.
- The last result and its timestamp are stored and shown until the next check, so the section
  is useful without spending a call.
- Each failing API shows a one-line hint about the usual cause (API not enabled in the
  project, key restriction excluding the server IP, quota cap reached).
- The check is rate-limited to once per minute to prevent it being used as a call generator.

> NOTE: the check consumes a small number of API calls by design. It is the one place the
> product deliberately calls Google outside a caching path, and it is behind an explicit
> button press for exactly that reason. A slow scheduled probe is a possible later addition;
> it is deliberately not built in v1.

### AC-11 — Main admin: see how much is in the system

**As the main admin, I can see counts of the things in this trip at a glance.**

- Counts: families, members, invites outstanding, polls (open / closed), suggestions by
  status, comments, itinerary items, check-ins, notifications unread across the trip.
- Each count is a plain number with a label; counts that are zero are shown as zero, not
  hidden.
- Counts for features not yet built read zero rather than erroring, so the console works from
  M1 onward.

### AC-12 — Main admin: know when someone is stuck on the password screen

**As the main admin, I can see who still has to change their password.**

- The member table flags anyone with `must_change_password` set.
- This includes the seeded admin before their first change, and anyone I have reset.
- The flag clears automatically once they change it.

## Permissions

Every action in this feature requires the main admin. The table is short by design.

| Action | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| Reach the trip setup screen (AC-0) | yes, until setup is done | no | no | no |
| See the `Admin` nav entry | yes | no | no | no |
| Read trip settings | yes | no (reads the trip via `auth/me`) | no | no |
| Edit trip name / dates / timezone | yes | no | no | no |
| Change the stage (forward or back) | yes | no | no | no |
| Read / edit category voting modes | yes | read-only, via the voting UI | read-only, via the voting UI | no |
| Read the family / member overview | yes | no (uses the `families` view) | no | no |
| Reset a user's password | yes | no | no | no |
| Remove a user from the trip | yes | no | no | no |
| Read / edit instance settings | yes | no | no | `instance_name` only, via the public settings endpoint |
| Run the Google API check | yes | no | no | no |
| Read platform stats | yes | no | no | no |

"Read-only, via the voting UI" means other roles see the *effect* of the category mode —
whether they are shown a 1–10 scale or thumbs — not the settings editor.

## Stage availability

| Capability | Planning | Holiday | End |
|---|---|---|---|
| Trip setup screen (AC-0) | shown on first login (before Planning) | n/a | n/a |
| Read every section of the console | yes | yes | yes |
| Edit trip name / dates / timezone | yes | yes | no (`409`) |
| Planning → Holiday | yes | n/a | n/a |
| Holiday → End | n/a | yes | n/a |
| Backward stage correction | n/a | yes (→ Planning) | yes (→ Holiday) |
| Edit category voting modes | yes | yes | no (`409`) |
| Reset a password | yes | yes | yes |
| Remove a user | yes | yes | no (`409`) |
| Edit instance settings | yes | yes | yes |
| Run the Google API check | yes | yes | yes |
| Read stats | yes | yes | yes |

Password reset, instance settings, the API check and stats stay available in End because they
are account and platform operations, not trip data — the same principle foundation applies to
password and theme changes. Removing a user in End is refused because it would alter the
archived record of who was on the trip.

## Out of scope

- Any editing UI that duplicates `families` — the console links into it instead.
- Per-poll voting-mode override (see the NOTE on AC-5).
- Email of any kind, including password-reset emails and admin alerts.
- Audit logging beyond the stage-transition record. A general audit trail is not in v1.
- Multi-trip management: creating, switching or archiving trips. The schema is multi-trip; the
  v1 console configures the single active trip.
- Transferring the main-admin role to another user.
- Backup and restore controls. Backups are an ops task documented in `deploy/README.md`.
- Editing another user's display name or theme.
- A scheduled Google API health probe.
- Bulk member import.
