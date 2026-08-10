# families — Design

**Reads first:** `plan/architecture.md`, `plan/design-system.md`, `plan/features/foundation/`,
and `requirements.md` in this directory.

## Data model

### `families` (exists in `plan/architecture.md`)

`id`, `created_at`, `updated_at`, plus:

| Column | Notes |
|---|---|
| `trip_id` | every trip-scoped table carries it; never assume a single trip |
| `name` | unique per trip (see additions below) |
| `color` | the token slot, stored as a small int 1–8 mapping to `--family-1…8` |
| `home_address` | free text as entered |
| `home_lat`, `home_lng` | nullable until geocoded |
| `home_geocoded_at` | nullable; null means never successfully geocoded |

> `architecture.md` describes `color` as "token slot". Stored as `smallint` 1–8 rather than
> a token string, so the constraint "one slot per family per trip" is a plain unique index and
> the design system can rename tokens without a data migration.

**PROPOSED ADDITION — `families.home_locality`** (text, nullable). The coarse label
(town/locality) returned by the geocode, shown to members of other families who must not see
the full street address (FM-4). Without it, the API would have to either leak the full address
or re-call Geocoding to derive a locality — both unacceptable under the cost rule.

**PROPOSED ADDITION — `families.geocode_status`** (text: `pending` / `ok` / `not_found` /
`error`, default `pending`) and **`families.geocode_error`** (text, nullable). Needed to
distinguish "never tried", "tried and the address is not a place", and "tried and Google was
unreachable" (FM-3), which have different UI states and different retry semantics.

**PROPOSED ADDITION — unique index** on `(trip_id, lower(name))` and on `(trip_id, color)`.

### `family_members` (exists)

`family_id`, `user_id`, `role` (`admin` / `member`). Foundation created the table bare.

**PROPOSED ADDITION — unique index** on `(user_id)`. A user belongs to exactly one family
(`plan/overview.md`: "belongs to one family"). Enforcing it in the database prevents a class
of bug that would otherwise be caught only in application code.

> NOTE: this constraint is per-user, not per-user-per-trip, which is stricter than a fully
> multi-trip schema would need. It is correct for v1 and matches the stated rule. If real
> multi-trip support arrives, this becomes `(user_id, trip_id)` via `family_members.trip_id`
> or a join through `families.trip_id` — flagged here so the change is a known one.

### `invites` (exists)

`family_id` (nullable — null means the invite creates a new family), `token`, `expires_at`,
`created_by`, `used_by` (nullable).

**PROPOSED ADDITION — `invites.trip_id`** (uuid). A new-family invite has no `family_id`, so
without this there is nothing to say which trip it belongs to.

**PROPOSED ADDITION — `invites.token_hash`** replacing plaintext `token` storage. The token is
a bearer credential; store only its sha256, exactly as foundation does for session cookies.
The raw token is shown once at creation and never retrievable afterwards — the UI states this.

**PROPOSED ADDITION — `invites.revoked_at`** (timestamptz, nullable) and **`invites.used_at`**.
`used_by` alone cannot express "revoked before use" (FM-5).

An invite is usable when `used_by is null and revoked_at is null and expires_at > now()`.

### `users` (exists, from foundation)

Read and written here for registration (FM-7) and display-name edits (FM-11).

## REST endpoints

All under `/api/v1`. Every mutating route also carries
`Depends(require_stage("planning", "holiday"))` unless noted; the End stage therefore returns
`409 stage_forbidden` without per-route logic.

### Families

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| GET | `/families` | — | `[FamilyOut]` | `require_member` |
| POST | `/families` | `{name, color?, home_address?}` | `FamilyOut` | `require_main_admin` |
| GET | `/families/{id}` | — | `FamilyDetailOut` | `require_member` |
| PATCH | `/families/{id}` | `{name?, color?}` | `FamilyOut` | `require_family_admin(id)` |
| PUT | `/families/{id}/home` | `{home_address}` | `FamilyDetailOut` | `require_family_admin(id)` |
| DELETE | `/families/{id}/home` | — | `204` | `require_family_admin(id)` |
| POST | `/families/{id}/home/geocode` | — | `FamilyDetailOut` | `require_family_admin(id)` |
| DELETE | `/families/{id}` | — | `204` | `require_main_admin` |

`FamilyOut`:

```
{id, name, color, member_count,
 home_locality: str|null,
 home_placed: bool,
 geocode_status: "pending"|"ok"|"not_found"|"error"}
```

`FamilyDetailOut` adds `members: [MemberOut]`, and adds `home_address`, `home_lat`,
`home_lng`, `home_geocoded_at` **only when the caller is a member of that family or the main
admin**. The serialiser makes this decision server-side; the frontend never receives a field
it is not entitled to see.

`MemberOut`: `{user_id, username, display_name, role, joined_at, is_main_admin}`.

`POST /families/{id}/home/geocode` is the explicit retry from FM-3. `PUT .../home` geocodes
inline and returns the result so the user can confirm it; if the address string is byte-identical
to the stored one and `geocode_status == "ok"`, it is a no-op and no external call is made.

### Members

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| GET | `/families/{id}/members` | — | `[MemberOut]` | `require_member` |
| PATCH | `/families/{id}/members/{user_id}` | `{role: "admin"\|"member"}` | `MemberOut` | `require_family_admin(id)` |
| DELETE | `/families/{id}/members/{user_id}` | — | `204` | `require_family_admin(id)` |

### Invites

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| GET | `/invites` | `?family_id=` | `[InviteOut]` | `require_family_admin` for own; `require_main_admin` for all |
| POST | `/invites` | `{family_id: uuid\|null, expires_in_hours: 24\|168\|720}` | `InviteCreatedOut` | see below |
| POST | `/invites/{id}/revoke` | — | `204` | creator's family admin, or main admin |
| GET | `/invites/token/{token}` | — | `InvitePreviewOut` | **none — public** |
| POST | `/invites/token/{token}/accept` | `{username, display_name, password, family_name?}` | `{user, csrf_token}` + session cookie | **none — public**, rate-limited |

`POST /invites` permission: `family_id` non-null requires `require_family_admin(family_id)`;
`family_id` null requires `require_main_admin` (FM-6).

`InviteCreatedOut`: `{id, url, expires_at, family: {id, name}|null}` — `url` is
`PUBLIC_BASE_URL` + `/join/<raw-token>`, returned exactly once.

`InviteOut` (listing): `{id, created_by, created_at, expires_at, used_by, used_at, revoked_at, family, status}` —
no token, raw or hashed.

`InvitePreviewOut`: `{instance_name, trip_name, trip_stage, mode: "join"|"create_family", family_name: str|null, valid: bool, reason: "expired"|"used"|"revoked"|"unknown"|null}`.
When `valid` is false, every other field except `instance_name` is null — an invalid token
reveals nothing (FM-7).

`family_name` in the accept body is required when the invite's mode is `create_family` and
rejected when it is `join`.

### Profile

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| PATCH | `/me` | `{display_name}` | `UserOut` | `require_member`; allowed in all stages |
| POST | `/auth/password` | foundation's endpoint, reused | `204` | authenticated |
| PATCH | `/me/preferences` | foundation's endpoint, reused | prefs | `require_member` |

## Geocoding service

Lives in `server/app/services/google.py`, alongside the other Google callers. Contract:

```
async def geocode(address: str) -> GeocodeResult | None
GeocodeResult = {lat, lng, formatted_address, locality}
```

Rules, following `plan/architecture.md` and `CLAUDE.md`:

- Called **only** from the home-set and home-retry endpoints. Never from a list or render
  path. A `GET /families` request must never be able to trigger an external call, no matter
  what state the row is in.
- Uses `GOOGLE_MAPS_SERVER_KEY` (the IP-restricted key), never the browser key.
- The result is written to `families` and kept forever, per the cost table ("Geocoding — once
  per family home address — cached forever in `families`").
- Wrapped behind an interface with a fake implementation for tests; the suite never reaches
  Google (`CLAUDE.md`).
- `locality` is derived from the response's address components (`postal_town`, else
  `locality`, else `administrative_area_level_2`).
- Missing server key → `geocode_status = "error"`, `geocode_error = "no_api_key"`, HTTP `200`
  with the family saved. Setting up a key is an admin task, not a user error.

Because geocoding is a synchronous inline call on save, the endpoint has a short timeout
(5 seconds); on timeout the address is saved with `geocode_status = "error"` and the user is
offered retry. Nothing blocks on Google.

## WebSocket events

`plan/architecture.md` lists five reserved event names; that list is explicitly the shape of
the channel rather than a closed set. These are **PROPOSED ADDITIONs** to it:

| Event | Emitted when | Payload | Consumers |
|---|---|---|---|
| `family.created` | a family is created | `{family: FamilyOut}` | families table, map |
| `family.updated` | name, colour, or home/geocode changes | `{family: FamilyOut}` | families table, map pins, any family-coloured UI |
| `family.deleted` | an empty family is deleted | `{family_id}` | families table, map |
| `member.joined` | an invite is accepted, broadcast to the trip room | `{family_id, member: MemberOut}` | member lists, counts |
| `member.updated` | a role changes | `{family_id, member: MemberOut}` | member lists |
| `member.removed` | a member is removed | `{family_id, user_id}` | member lists, counts |

`family.updated` carries `FamilyOut` only — the coarse, non-sensitive shape. Full addresses are
never broadcast, because a socket is joined to the whole trip room and would deliver them to
other families. A client entitled to the full address refetches `GET /families/{id}`.

Consumed: `stage.changed` (from `admin-console`) — on `end`, the UI drops to read-only.

The removed user's own socket receives `member.removed` via `send_user` and the client
refetches `auth/me`, which now returns `family: null`; the shell then shows the "you are not
on this trip" state rather than a broken screen.

## UI behaviour

Per `plan/design-system.md`. Every value comes from a semantic token.

### Families view (desktop)

Map centre (~62%) with a right side panel (~38%), matching the product's core pattern — the
same dataset as a table and as a map overlay.

- **Map:** one home pin per family with `home_lat/lng`, filled with that family's
  `--family-N` token, labelled with the family name. Colour is never the only carrier —
  the label is always present. Families without coordinates are listed under the table with a
  "not placed" chip, so they are not silently invisible.
- **Table:** columns — colour swatch, name, members, home locality, status. Tri-state sort
  (asc → desc → original), sticky header, full-row click target, tabular figures on the member
  count, right-aligned numerics. Density from spacing tokens.
- **Selection:** clicking a row or a pin opens that family in the side panel. The panel holds
  the family header (colour swatch, name), the home block, the member list, and the invite
  block. Admin controls appear only for callers who are entitled to them, and the backend
  refuses regardless.

### Families view (mobile)

Full-bleed map, families list as a bottom sheet at the ~40% snap; selecting a family raises it
to ~90%. All targets ≥ 44px. Nothing analytical is put in a modal — the sheet is the panel.

### Home address editing

An inline form in the side panel. Free-text field, `Save`. On save the button shows an inline
spinner (sub-second-to-few-second wait — a spinner, not a skeleton). The result appears as a
confirmation block: the formatted address the geocoder returned and a small static map
preview, with `Looks right` / `Edit`. Only on confirmation is the coordinate treated as final.

States, each with distinct text and an icon, never colour alone:

- **Not set** — empty state: "No home address yet — add one so we can show travel times."
- **Placed** — formatted address plus locality, and the date it was placed.
- **Not found** — "We could not find that address on the map. Check it and try again." Retry
  action.
- **Error** — "We could not reach the mapping service. Your address is saved." Retry action.
  If the cause is `no_api_key` and the viewer is the main admin, the message links to the
  admin console's Google status section instead.

### Invites

In the family side panel, an `Invite someone` action. A small form (expiry select, default
7 days) produces the link in a copy-once block: the URL, a `Copy link` button, the expiry, and
a plain line stating the link is shown only now and cannot be retrieved later. A toast confirms
the copy — a transient confirmation of the user's own action, which is exactly what toasts are
for.

Outstanding invites list below: created by, created, expires, status chip
(`active` / `used` / `expired` / `revoked`), and a `Revoke` action on active ones. Revoke is a
low-stakes reversible-by-reissue action, so it uses undo rather than a confirm dialog.

The main admin's family view also offers `Invite a new family`, which creates the
`family_id: null` variant. It sits visually apart from the per-family invite so the two are
not confused.

### Join / registration screen

A standalone route `/join/<token>` outside the app shell — no nav rail, no tabs, because the
visitor is not yet a member.

- Fetches the preview first and renders it before asking for anything: instance name, trip
  name, and either "You are joining the <name> family" or "You will create a new family".
- Invalid token: a single plain card — "This invite link is no longer valid" plus the reason
  in ordinary words and "Ask whoever invited you for a new link." No trip details.
- Valid: the form — username, display name, password, confirm, plus family name when the mode
  is `create_family`. All six field states styled; validate on blur; username-taken shows on
  that field.
- Trip in the End stage: the preview says the trip has finished and the form is not shown.
- Already logged in: the preview is shown with an explanation that joining needs a separate
  account, and a `Log out and continue` action (FM-8).

### Profile page

One page reached from the nav rail: display name (inline edit, save on blur with an undo
toast), password change (foundation's form), theme control (foundation's control), plus a
read-only block showing username, family and role. Available in every stage, including End.

### Empty states

- No families: "No families yet — create the first one" with the action inline (main admin);
  members see "The trip organiser hasn't added any families yet."
- Family with one member: no special state, but the invite action is given prominence.
- No outstanding invites: "No open invites."

### Loading

Skeletons for the families table and the side panel structure; spinners for the inline
save/geocode waits. Optimistic updates for rename and colour change, rolled back if the
request fails.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| Ninth family created | `409` code `no_color_slots`, message: the palette supports eight families |
| Colour slot taken | `409` code `color_taken`, message names the holding family |
| Duplicate family name on the trip | `409` code `name_taken` |
| Delete a family with members | `409` code `family_not_empty`; the message says to remove members first |
| Remove the last family admin | `409` code `last_family_admin`; the message says to promote someone first |
| Demote the last family admin | Same as above |
| Remove or demote the main admin | `403` code `main_admin_protected` |
| A family admin acts on another family | `403 forbidden`; the UI never showed the control |
| Member tries to read another family's full address | The field is simply absent from the response; no error, no leak |
| Geocode returns no result | `200`, saved, `geocode_status = "not_found"` |
| Geocode times out or errors | `200`, saved, `geocode_status = "error"`, retry offered |
| No server API key configured | `geocode_status = "error"`, `geocode_error = "no_api_key"` |
| Re-saving the identical address | No external call; `200` with the existing values |
| Address cleared | `home_address`, lat, lng, locality, `home_geocoded_at` all nulled; `geocode_status` back to `pending`; the home pin disappears for everyone |
| Invite token unknown, expired, used or revoked | `200` with `valid: false` and a reason; never `404`, so probing cannot distinguish an unknown token from an expired one |
| Two people open the same single-use invite and both submit | The second gets `409 invite_already_used`; enforced by a conditional update on `used_by is null`, not by a read-then-write |
| Invite accepted after its family was deleted | `409 invite_family_missing`, with a message to request a new link |
| Username taken during registration | `409 username_taken` on that field |
| Registration while the trip is in End | Refused; the preview already said so |
| Logged-in user accepts an invite | Refused with `409 already_member`; the UI offered log-out first |
| A user is removed while they have the app open | Their socket gets `member.removed`; the client refetches `auth/me` and shows a "you are no longer on this trip" screen rather than erroring |
| Colour changed while another user views the map | `family.updated` repaints pins live |
| Stage becomes `end` mid-edit | The save returns `409 stage_forbidden`; the UI shows the archive banner and switches to read-only |
| Geocode succeeds but the family is deleted meanwhile | The write is a no-op; no error surfaced |

## Dependencies and hand-offs

- **Depends on `foundation`** for sessions, CSRF, `require_member` /
  `require_family_admin` / `require_main_admin` / `require_stage`, the error envelope, the
  WebSocket broadcast helpers, and the password endpoint.
- **Provides to `distances`** the geocoded `home_lat`/`home_lng` that Distance Matrix pairs are
  computed from. That feature must treat a null home as "no distances available", not as an
  error.
- **Provides to `admin-console`** the family and member listing used by its overview section.
  Account-level operations (reset password, delete user) live there, not here.
- **Provides to every map feature** the `--family-N` colour slot used for pins and labels.
