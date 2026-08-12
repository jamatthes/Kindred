# families — Design

**Reads first:** `plan/architecture.md`, `plan/design-system.md`, `plan/features/foundation/`,
and `requirements.md` in this directory.

> **Roles (revised 2026-08-11).** This feature owns the hierarchy: **owner / organiser** at
> trip level, **head of family / spouse / member** at family level, defined in
> `requirements.md` > Roles. Throughout this document, "main admin" in any older sentence
> means **owner or organiser** (`require_organiser`); the powers reserved to the owner alone
> say so explicitly. "Family admin" means **head of family**, and a spouse has the same powers
> **except where the head is the target of the action**.
>
> NOTE: `admin-console` and `holiday-stage` inherit this hierarchy rather than restating it.
> `admin-console` additionally owns the organiser-management endpoints and UI — this feature
> creates the `trip_organisers` table and the `require_owner` / `require_organiser`
> dependencies, so those screens are added over a hierarchy that already works.

## Data model

### `families` (exists in `plan/architecture.md`)

`id`, `created_at`, `updated_at`, plus:

| Column | Notes |
|---|---|
| `trip_id` | every trip-scoped table carries it; never assume a single trip |
| `name` | unique per trip (see additions below) |
| `color` | the token slot, stored as a small int 1–24 mapping to `--family-1…24`; **nullable** since 2026-08-11 (see "Family colour palette" below) |
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

**PROPOSED ADDITION — `families.location_sharing_allowed`** (bool, not null, default `true`)
and **`families.member_location_default`** (bool, not null, default `false`). The two halves
of the head or spouse's location policy (FM-15). They are separate columns because they answer
different questions and change at different times: `location_sharing_allowed` is a live
switch read on every map query, `member_location_default` is a seed value read exactly once
per member, when they join.

> Defaults are chosen so that a family which never opens these settings behaves exactly as
> the product did before they existed: the family is allowed on the map, and each member is
> off until they say otherwise.

### `family_members` (exists)

`family_id`, `user_id`, `role`. Foundation created the table bare.

**PROPOSED ADDITION — `role` becomes `head` / `spouse` / `member`** (check-constrained;
`admin` renamed to `head`, `spouse` new). A household usually has two adults, and making one
of them a plain member misdescribes the family the software is modelling. **Exactly one `head`
per family**, enforced by a partial unique index on `(family_id) WHERE role = 'head'`: a
family with two heads and the spouse asymmetry between them is a deadlock nobody can
unpick, and a family with none can only be repaired by an organiser.

A spouse holds the head's powers over the family with one exception, and the exception is
evaluated against the **target** of the action rather than the actor's role: a spouse may not
remove the head, change the head's role, or change the head's visibility switches. Expressed
as one predicate so it cannot be applied to three routes and forgotten on a fourth:

```
spouse_may_act_on(actor, target) = not (actor.role == "spouse" and target.role == "head")
```

Transferring the head role is a single action, not a promote-then-demote: the outgoing head
becomes a `spouse` in the same transaction that the incoming one becomes `head`. Two
statements would leave a window with two heads or none, and the second could fail.

**PROPOSED ADDITION — unique index** on `(user_id)`. A user belongs to exactly one family
(`plan/overview.md`: "belongs to one family"). Enforcing it in the database prevents a class
of bug that would otherwise be caught only in application code.

**PROPOSED ADDITION — `family_members.location_sharing_allowed`** (bool, not null, default
`true`). The per-member half of FM-15 — the head or spouse's decision that this particular
person is not shown, independent of whether that person has consented. It lives on
`family_members` rather than on `users` because it is a fact about a person's place in a
family, and it must disappear along with the membership when they leave.

> NOTE: this constraint is per-user, not per-user-per-trip, which is stricter than a fully
> multi-trip schema would need. It is correct for v1 and matches the stated rule. If real
> multi-trip support arrives, this becomes `(user_id, trip_id)` via `family_members.trip_id`
> or a join through `families.trip_id` — flagged here so the change is a known one.

### `trip_organisers` (created here)

**PROPOSED ADDITION — new table.** `trip_id`, `user_id`, `granted_by` (nullable, FK → `users`
`ON DELETE SET NULL`), `created_at`. Unique on `(trip_id, user_id)`, indexed on `trip_id`.

No `updated_at`: the row's existence *is* the grant, so there is nothing to mutate — revoking
is a delete. `granted_by` is nullable so removing the account that made a grant does not take
the grant with it.

Written **only** by the owner (`require_owner`). The table is created here because the
permission dependencies in this feature read it from the first route; the endpoints and UI
that manage it belong to `admin-console` (FM-17).

### `invites` (created here — see NOTE)

> NOTE (implementation, Phase 1): `invites` and `attachments` are **created** by the schema
> migration, not altered onto an existing table. `plan/architecture.md` lists both, but
> foundation created only the tables it actually used, so neither existed. Consequences: the
> columns `tasks.md` says to "add" to `invites` are part of the create, and there is no
> plaintext `token` column to replace — the table is born storing only `token_hash`.
> `attachments` is created with the columns `architecture.md` names plus `thumb_path` and
> `byte_size`: avatars emit two renditions (256px and 64px) and `MemberOut` exposes both as
> `avatar_url` and `avatar_thumb_url`, so the small one needs somewhere to live.

> NOTE (implementation, Phase 1): `families.color` is **NOT NULL**. `0001` created it
> nullable; a family with no colour slot cannot be drawn on the map or in any list, and the
> `(trip_id, color)` unique index would not constrain nulls in any case. The table is empty
> when this ships — foundation seeds no family — so there is nothing to backfill.

### Family colour palette (ruling, added 2026-08-11)

The palette grows from 8 to **24** curated colours. Slots 1-8 keep their exact hex values in
both themes — existing families and demo data never shift.

**Picking a colour.** The family-setup screen (FM-13) gains a 24-swatch grid; the founder
picks their family's colour there, rather than the server silently assigning the lowest free
slot. Swatches already claimed by another family on the trip are shown disabled with a
"taken" treatment and an accessible name (e.g. "Coral (taken)"); the grid defaults to the
first free slot pre-selected, so submitting the form having touched nothing still succeeds —
this is what keeps `web/e2e/tests/04-ws-liveness.spec.ts` (which only fills in a name) green.
A head or spouse can change their family's colour later from `FamilyPanel`, reusing the same
picker component, same exclusivity rule, gated to the family-manager permission
(`require_family_head_or_spouse`), with an optimistic update rolled back on failure and a
`family.updated` broadcast so every connected session recolors without a reload.

**Overflow: the colour wheel.** Once all 24 slots are claimed on a trip, the 25th and every
later family gets a free colour wheel — a native `<input type="color">`, styled minimally, no
new dependency — instead of a slot. The server enforces the gate: a custom hex is accepted
**only** when `next_free_color` returns `None` for that trip; a custom colour submitted while
a slot is still free is refused (`422 custom_color_not_allowed`), and a slot submitted once
the palette is exhausted is refused exactly as it always was if it is taken
(`409 color_taken`) — exhaustion does not relax slot exclusivity, it only opens the second
path.

**Data model.** `families.color` (smallint) becomes nullable; a new nullable
`families.color_custom` (text, `#RRGGBB`) holds the wheel-picked value. A `CHECK` constraint,
`ck_families_color_xor`, enforces that **exactly one** of the two is set — this over the
alternative of a separate `is_custom_color` boolean flag, because a boolean-plus-two-nullable-
columns design can still represent "flag says custom but `color_custom` is null" as a valid
row, while the XOR constraint makes that state unrepresentable rather than merely
discouraged. `next_free_color` (and therefore the palette-exhaustion check) only ever looks at
`color`, so custom colours never occupy or free a slot.

**Rendering.** One helper, `familyColor(family): string` (`web/src/design/familyColor.ts`),
returns `var(--family-N)` for a slot or the raw hex for a custom colour. Every call site — the
identity badge ring, map pins, family cards, presence stack — goes through it; nothing branches
on slot-vs-custom itself. `IdentityBadge`'s `familyColor` prop is therefore the resolved CSS
colour string, not a bare slot number, so the component itself never has to know which case it
is drawing.

**Distinguishability is best-effort, not a guarantee.** The 24 in-palette colours were chosen
by walking the hue circle formed by the original 8 and subdividing its gaps proportionally to
their size, landing close to an even ~15° spacing while keeping the original anchors
byte-identical. Wheel-picked overflow colours escape both that spacing discipline and the
light/dark tuning applied to the palette (see `tokens.semantic.css`'s comments on the 9-24
block) — a founder can pick a hex indistinguishable from an existing family's. This is
accepted rather than mitigated (e.g. by rejecting near-duplicate hexes) because it only
arises from the 25th family on a single trip, and because the identity badge ring is already
documented as never the sole carrier of identity: a name label or hover always accompanies
it (`plan/design-system.md`).

**Taken-set visibility.** `GET /families/palette` (new, see REST endpoints below) exposes
`{taken_colors, exhausted}` for the active trip. It is reachable by any authenticated user on
the trip regardless of family membership — including a founder mid-setup, who has no
`family_members` row yet and therefore cannot call `GET /families` (`require_member`) — because
the payload is not sensitive: which of 24 numbered slots are in use, and whether the palette is
full, leaks nothing an address or a name would.

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

**PROPOSED ADDITION — `invites.mode`** (text: `join` / `create_family`, not null, default
`join`). This section says a null `family_id` means "creates a new
family", and the `invites` schema entry says `family_id` is `ON DELETE SET NULL` so a deleted
family leaves the invite reportable as `invite_family_missing`. Those cannot both be true:
deleting a family turns its outstanding join invites into family-founding ones, and accepting
one then creates an account and drops the visitor on a family setup screen they were never
invited to — a `201` where the edge-case table below promises a `409`. With `mode` stated,
`family_id is null` means exactly one thing:

| `mode` | `family_id` | Meaning |
|---|---|---|
| `create_family` | null | FM-6 — the recipient founds their own family |
| `join` | set | FM-5 — join that family |
| `join` | null | the family was deleted → `invite_family_missing` |

`InvitePreviewOut.reason` gains `family_missing` for the same reason: the visitor should learn
this before filling in a registration form, not after submitting one.

### `users` (exists, from foundation)

Read and written here for registration (FM-7) and profile edits (FM-11).

**PROPOSED ADDITION — `users.first_name`** (text, not null) and **`users.last_name`** (text,
not null, may be the empty string). The product needs a person's name in two structurally
different shapes: initials for the map badge, and a full name for its hover label
(`plan/features/holiday-stage/`, HS-11). `display_name` alone cannot supply either reliably —
splitting it on whitespace gives the wrong answer for a mononym ("Mum" → "M"), for a nickname
("jm" → "J"), and for anyone with a middle name in the field.

`display_name` stays, and stays separately editable. It is seeded to
`"{first_name} {last_name}".strip()` at registration, so nobody has to fill in three name
fields to sign up, and a member who goes by something other than their given name can change
it without breaking their badge.

> NOTE: `last_name` is nullable-by-emptiness rather than nullable, so the initials rule is
> total. A member with a single name gets a one-letter badge, which is correct rather than a
> degraded case to handle at every call site.

**PROPOSED ADDITION — `users.avatar_attachment_id`** (uuid, nullable, FK → `attachments`,
`ON DELETE SET NULL`). See the Avatars section below.

## REST endpoints

All under `/api/v1`. Every mutating route also carries
`Depends(require_stage("planning", "holiday"))` unless noted; the End stage therefore returns
`409 stage_forbidden` without per-route logic.

### Families

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| GET | `/families` | — | `[FamilyOut]` | `require_member` |
| GET | `/families/palette` | — | `{taken_colors: [int], exhausted: bool}` | any authenticated trip member **or** a pending founder (no `require_member`; added 2026-08-11, see "Family colour palette") |
| POST | `/families/mine` | `{name, home_address?, color?, color_custom?}` | `FamilyDetailOut` | `require_pending_family` |
| GET | `/families/{id}` | — | `FamilyDetailOut` | `require_member` |
| PATCH | `/families/{id}` | `{name?, color?, color_custom?}` | `FamilyOut` | `require_family_head_or_spouse(id)` |
| PATCH | `/families/{id}/location-policy` | `{sharing_allowed?, member_default?}` | `FamilyDetailOut` | `require_family_head_or_spouse(id)` |
| PUT | `/families/{id}/home` | `{home_address}` | `FamilyDetailOut` | `require_family_head_or_spouse(id)` |
| DELETE | `/families/{id}/home` | — | `204` | `require_family_head_or_spouse(id)` |
| POST | `/families/{id}/home/geocode` | — | `FamilyDetailOut` | `require_family_head_or_spouse(id)` |
| DELETE | `/families/{id}` | — | `204` | `require_organiser` |

> REMOVED 2026-08-11 (user ruling): **`POST /families`**, the bare create that took a name and
> made a family with nobody in it. It was `require_organiser`-guarded and produced exactly one
> artefact — a family shell whose creator was not a member — which is the state FM-1's
> "no memberless families" invariant now forbids. The organiser's path to a new family is
> `POST /invites` with `family_id: null` (FM-6), which already exists, and the family is born
> with its head in the same transaction that creates it. The route is gone rather than
> re-pointed: `GET /families` still answers on that path, so a client that has not been updated
> gets `405`, which is a clearer answer than a silently repurposed `201`.
>
> Two things that were only ever exercised through it go with it: the request field `color` (no
> other route accepted a caller-chosen colour at creation — the lowest free slot was assigned
> and `PATCH /families/{id}` changed it afterwards, with the taken slots visible), and
> `FamilyCreateIn`.
>
> REVISED 2026-08-11 (24-colour palette ruling): `POST /families/mine` now **does** accept a
> caller-chosen `color` or `color_custom`, because that route is the only creation path left
> and its caller — the founder, on the family-setup screen — is shown the taken-slot grid right
> there. This does not reopen the withdrawn capability: nobody creates a family *for* another
> user here, and the head-in-the-same-transaction invariant is unchanged.

`POST /families/mine` is now the **only** route in the product that creates a family, and the
one route in this feature that a user with no family may call. That is the enforcement point
for the invariant: there is no second code path that could forget to write a membership row.

Its dependency `require_pending_family` (**PROPOSED ADDITION** to foundation's set, defined
here because this is the only route that uses it) allows a caller with **no `family_members`
row** who is either:

* **an invited founder** — their `used_by` appears on a consumed invite with
  `mode = 'create_family'`; or
* **the trip's owner** — `trips.owner_user_id`, or the seeded platform admin before a trip
  exists (added 2026-08-11; see FM-13 "The owner takes this step too"). Nobody invites the
  owner to their own instance, so ownership is the evidence that stands in for the invite.

Anyone else gets `403 forbidden` — in particular an existing member cannot use it to acquire a
second family, and someone removed from the trip cannot use it to re-admit themselves.

> The invite half of the predicate keys on `invites.mode`, not on `family_id is null`. Those
> two stopped being the same question when `family_id` became `ON DELETE SET NULL`
> (`plan/architecture.md`): deleting a family turns its consumed join invites into rows with a
> null `family_id`, which under the old predicate would have made every member of that family
> "pending" — a licence to found a family, handed out by an unrelated deletion. `mode` is the
> column that was added to say what an invite is *for*, and this is one of the places that has
> to ask.

In one transaction it: creates the family on the active trip with the lowest free colour slot,
writes the `family_members` row with `role = 'head'`, seeds that user's
`user_settings.live_location_enabled = true` (FM-15), and geocodes the home address if one was
supplied. It is idempotent on a retry that arrives after the first succeeded: the second call
sees the caller now has a family and returns `409 already_has_family`, which the client treats
as success and re-reads `auth/me`.

`PATCH /families/{id}/location-policy` is the head or spouse's control from FM-15. Setting
`sharing_allowed: false` does **not** write to any member's `user_settings` — it is a filter
applied at read time, so turning it back on restores exactly the set of members who had
consented, rather than silently re-enabling people who had turned themselves off.

`FamilyOut`:

```
{id, name, color: int|null, color_custom: str|null, member_count,
 home_locality: str|null,
 home_placed: bool,
 geocode_status: "pending"|"ok"|"not_found"|"error",
 location_sharing_allowed: bool}
```

`color` and `color_custom` are mutually exclusive per the `ck_families_color_xor` constraint
(see "Family colour palette" above); exactly one is non-null. Clients resolve either through
`familyColor(family)` and never branch on which is set themselves.

`FamilyDetailOut` adds `members: [MemberOut]` and `member_location_default: bool`, and adds
`home_address`, `home_lat`, `home_lng`, `home_geocoded_at` **only when the caller is a member
of that family, the owner, or an organiser**. The serialiser makes this decision server-side; the
frontend never receives a field it is not entitled to see.

`member_location_default` is in `FamilyDetailOut` rather than `FamilyOut` because it is a
family's internal policy, not something other families need in a list.

`MemberOut`:

```
{user_id, username, first_name, last_name, display_name,
 avatar_url: str|null, initials: str,
 role, joined_at, is_owner, is_organiser,
 location_sharing_allowed: bool,          // the head or spouse's per-member switch
 location_sharing_enabled: bool|null}     // the member's own consent; null unless the
                                          // caller is that member, their family's head or
                                          // spouse, the owner, or an organiser
```

`initials` is computed server-side so every surface renders the same badge — the map, the
member list, the presence stack and the admin console cannot drift. Rule: first character of
`first_name` plus first character of `last_name`, uppercased; when `last_name` is empty, the
first character of `first_name` alone. Non-Latin scripts take the first grapheme cluster of
each, not the first byte.

`location_sharing_enabled` is deliberately not public. Whether someone has consented to share
is itself private: a member of another family can see a marker or no marker, and cannot tell
the difference between "not sharing" and "app closed".

`POST /families/{id}/home/geocode` is the explicit retry from FM-3. `PUT .../home` geocodes
inline and returns the result so the user can confirm it; if the address string is byte-identical
to the stored one and `geocode_status == "ok"`, it is a no-op and no external call is made.

### Members

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| GET | `/families/{id}/members` | — | `[MemberOut]` | `require_member` |
| PATCH | `/families/{id}/members/{user_id}` | `{role?: "head"\|"spouse"\|"member", location_sharing_allowed?: bool}` | `MemberOut` | `require_family_head_or_spouse(id)` |
| DELETE | `/families/{id}/members/{user_id}` | — | `204` | `require_family_head_or_spouse(id)` |

`location_sharing_allowed` on this route is the per-member half of FM-15 — the head or spouse
deciding that this particular person is not shown on the map. It writes
`family_members.location_sharing_allowed` and never touches
`user_settings.live_location_enabled`, for the same reason the family-level switch does not:
a permission and a consent are different things, and collapsing them would let an admin
revoke someone's own choice by flipping a switch twice.

**A head or spouse can only ever narrow visibility with these two controls.** There is no
request body, on any route in this feature, that turns another user's sharing on. That
invariant is what makes the promise in `plan/features/holiday-stage/requirements.md` ("nobody
can turn on another person's live-location sharing") still true now that family policy exists.

### Invites

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| GET | `/invites` | `?family_id=` | `[InviteOut]` | `require_family_head_or_spouse` for own; `require_organiser` for all |
| POST | `/invites` | `{family_id: uuid\|null, expires_in_hours: 24\|168\|720}` | `InviteCreatedOut` | see below |
| POST | `/invites/{id}/revoke` | — | `204` | that family's head or spouse, or an organiser |
| GET | `/invites/token/{token}` | — | `InvitePreviewOut` | **none — public** |
| POST | `/invites/token/{token}/accept` | `{username, first_name, last_name, password}` | `{user, csrf_token, next_step}` + session cookie | **none — public**, rate-limited |

`POST /invites` permission: `family_id` non-null requires
`require_family_head_or_spouse(family_id)`; `family_id` null requires `require_organiser`
(FM-6).

`InviteCreatedOut`: `{id, url, expires_at, family: {id, name}|null}` — `url` is
`PUBLIC_BASE_URL` + `/join/<raw-token>`, returned exactly once.

`InviteOut` (listing): `{id, created_by, created_at, expires_at, used_by, used_at, revoked_at, family, status}` —
no token, raw or hashed.

`InvitePreviewOut`: `{instance_name, trip_name, trip_stage, mode: "join"|"create_family", family_name: str|null, valid: bool, reason: "expired"|"used"|"revoked"|"unknown"|null}`.
When `valid` is false, every other field except `instance_name` is null — an invalid token
reveals nothing (FM-7).

The accept body no longer carries `family_name`. Naming the family is the family-setup
screen's job (FM-13), which means the two things a new head of family must decide — who they are
and what their family is called — are asked on two screens instead of one long form, and the
second is resumable.

`display_name` is not accepted either; it is derived server-side as
`"{first_name} {last_name}".strip()` and edited afterwards on the profile page. Asking for it
at registration would put three name fields in front of someone who has not yet seen the app.

What the accept route writes depends on the invite's mode:

| Mode | Writes | Resulting `next_step` |
|---|---|---|
| `join` | `users` row, `family_members` row with `role = 'member'`, `user_settings.live_location_enabled` seeded from that family's `member_location_default` | `app` |
| `create_family` | `users` row only — **no `family_members` row**, because no family exists yet | `setup_family` |

`next_step` is returned in the response body as well as being derivable from `auth/me`, so the
join screen can route immediately without a second round trip. It is foundation's field
(F-13) and its precedence rules are foundation's; this route only reports it.

> NOTE: a `create_family` acceptor is, between accepting and finishing setup, an authenticated
> user with no family. `require_member` refuses them everywhere by design (foundation F-9);
> `POST /families/mine` is the single route that admits them, via `require_pending_family`.

### Profile

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| PATCH | `/me` | `{first_name?, last_name?, display_name?}` | `UserOut` | `require_member`; allowed in all stages |
| PUT | `/me/avatar` | `multipart/form-data` (one image part) | `UserOut` | `require_member`; allowed in all stages |
| DELETE | `/me/avatar` | — | `UserOut` | `require_member`; allowed in all stages |
| POST | `/auth/password` | foundation's endpoint, reused | `204` | authenticated |
| PATCH | `/me/preferences` | foundation's endpoint, reused | prefs | `require_member` |

Avatar routes are exempt from the stage guard for the same reason password and theme are
(foundation): a profile picture is an account property, not trip data, and freezing a trip
must not freeze someone's face.

## Avatars

### Storage

An avatar is a row in the existing `attachments` table with `subject_type = 'user'` and
`subject_id = <user_id>`, written to the same local volume as every other attachment. No new
table. **PROPOSED ADDITION — `users.avatar_attachment_id`** (uuid, nullable, FK to
`attachments`, `ON DELETE SET NULL`), so resolving a user's avatar is a join the API already
makes rather than a lookup by subject on every member row.

At most one avatar row per user: `PUT` replaces, deleting the previous file and row in the
same transaction.

### Processing

Done on upload, server-side, so the map never fetches a 4MB phone photo:

- Accepted types: `image/jpeg`, `image/png`, `image/webp`. Anything else → `415
  unsupported_media_type` naming the accepted formats. The type is determined by sniffing the
  file's magic bytes, never from the client's `Content-Type` or the filename extension.
- Maximum upload 8MB → `413 file_too_large` above it. The limit is stated on screen before
  the picker opens, not only on failure.
- The image is decoded, EXIF-rotated to its display orientation, centre-cropped to a square,
  and resized to two WebP renditions: 256px (`avatar_url`) and 64px (`avatar_thumb_url`, what
  the map markers and member lists actually load). The original is not retained — it is
  strictly larger than anything the product renders.
- **All EXIF metadata is dropped in the re-encode, GPS tags included.** A product whose
  headline privacy promise is about location must not accept a photo carrying coordinates and
  serve it back to the whole trip.
- Animated inputs are flattened to their first frame. A moving avatar on a map marker is a
  distraction and defeats `prefers-reduced-motion`.
- Decoding is bounded (dimension and pixel-count caps) so a decompression-bomb image fails
  with `422 image_unreadable` instead of exhausting the container's memory.

### Serving

- `avatar_url` / `avatar_thumb_url` are paths under the attachments route, served by the API
  with a long `Cache-Control` and an ETag. The filename contains a content hash, so replacing
  an avatar changes the URL and no cache anywhere has to be invalidated.
- Avatars are readable by any member of the trip and by nobody else. An unauthenticated
  request for an avatar path is `401`, exactly like any other attachment.

## Location sharing policy

This feature owns the *policy*. `holiday-stage` owns the *location data* and the map. The
split matters: a family's settings outlive any one trip stage, and the map must not be the
place where permission is decided.

### The four inputs

Everyone on the trip is shown individually on the map — there is no per-family aggregation or
"representative member". Whether a given person's marker appears is one boolean, computed
server-side from four independent facts:

```
visible(user) =
      families.location_sharing_allowed          -- the head or spouse's master switch
  AND family_members.location_sharing_allowed    -- the head or spouse's per-member switch
  AND user_settings.live_location_enabled        -- the member's own consent
  AND <a fresh live_locations row exists>        -- they are actually sharing right now
```

Each term is owned by exactly one party, and no party can write another's:

| Term | Written by | Never written by |
|---|---|---|
| `families.location_sharing_allowed` | that family's head or spouse, or an organiser | members |
| `family_members.location_sharing_allowed` | that family's head or spouse, or an organiser | the member it describes |
| `user_settings.live_location_enabled` | the member themselves, and nobody else | any admin, ever |
| the `live_locations` row | the member's own browser, while the app is open | anyone |

**The three permission terms can only ever remove a marker.** A head or spouse flipping both of
their switches on does not put anyone on the map; it only stops preventing it. This is what
keeps `holiday-stage`'s HS-9 promise intact — "nobody, owner included, can turn on
another person's live-location sharing" — now that family policy exists alongside consent.

The one place a head or spouse's decision does reach a member's own setting is the **seed**
described next, and it applies only at the instant a member joins.

### The default, and why a seed is not a consent

`families.member_location_default` is copied into `user_settings.live_location_enabled` once,
when a member's `family_members` row is created. Afterwards the two are unrelated: changing
the family default never rewrites an existing member's setting, and a member who turns
themselves off stays off no matter what the default says.

A seeded-on member is **not** silently broadcasting. Two gates still stand between the seeded
value and a marker on the map:

1. The browser's own geolocation permission prompt, which only that person can answer, and
   which no server setting can pre-answer.
2. A one-time disclosure the first time the app is about to start sharing for a seeded-on
   member: the settings copy from `holiday-stage`, with `Start sharing` and `Not now`. `Not
   now` writes `live_location_enabled = false` — their own choice, recorded as their own.

So the family's default decides what the toggle *starts at*, not whether the person
shares. That distinction is the reason this addition does not contradict the "off by default,
privacy is a feature" stance in `plan/features/holiday-stage/requirements.md`; it is stated
here because a future reader will otherwise reasonably think it does.

The new head of family's own row is seeded `true` at `POST /families/mine`, per FM-15 — the person
who set the trip up is the one member whose marker the rest of the family expects to see. The
same two gates apply to them.

### Ordering

`families.location_sharing_allowed` is checked before the per-member switch, and both before
consent, purely so the API can answer "why is nobody from this family on the map" with a
single reason code rather than a set. The result is identical either way; the ordering exists
for the UI's explanation, not for correctness.

## Geocoding service

Lives in `server/app/services/google.py`, alongside the other Google callers. Contract:

```
async def geocode(address: str) -> GeocodeResult | None
GeocodeResult = {lat, lng, formatted_address, locality}
```

> NOTE (implementation, Phase 4): the return type is `GeocodeOutcome`
> (`{status: "ok"|"not_found"|"error", result: GeocodeResult|None, error: str|None}`), not
> `GeocodeResult | None`. The sketched signature cannot carry the third outcome this same
> section requires: `None` would have to mean both "this is not a place" (`not_found` — check
> what you typed) and "we could not reach Google" (`error` — retry later), which have
> different copy, different retry semantics and different rows in the edge-case table.
> `GeocodeResult` itself is unchanged. Google's own statuses map as: `OK` → `ok`,
> `ZERO_RESULTS` → `not_found`, and everything else (`REQUEST_DENIED`, `OVER_QUERY_LIMIT`,
> `INVALID_REQUEST`, `UNKNOWN_ERROR`) → `error` — those are conditions the operator fixes,
> so telling the user their address is wrong would send them to repair something that is not
> broken.

Rules, following `plan/architecture.md` and `CLAUDE.md`:

- Called **only** from the home-set and home-retry endpoints. Never from a list or render
  path. A `GET /families` request must never be able to trigger an external call, no matter
  what state the row is in.

> NOTE (implementation, Phase 5): there are **four** call sites, not two, and all four are
> mutating routes. `PUT /families/{id}/home` and `POST /families/{id}/home/geocode` are the
> two this section names; the third is `POST /families/mine`, which accepts an optional
> `home_address` because FM-13 says it does (a fourth, `POST /families`, went with the bare
> create on 2026-08-11) — an address
> supplied at creation has to be geocoded by something, and deferring it would mean a family
> created with an address sits unplaced until someone re-saves it. All four funnel through a
> single private helper, so the rule that actually matters is mechanically checkable: grep
> for `geocoder.geocode(` and there is exactly one hit, inside that helper, and no read route
> can reach it.
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
| `family.created` | a family is created (including via `POST /families/mine`) | `{family: FamilyOut}` | families table, map |
| `family.updated` | name, colour, home/geocode, or `location_sharing_allowed` changes | `{family: FamilyOut}` | families table, map pins, any family-coloured UI, **live-location layer** |
| `family.deleted` | an empty family is deleted | `{family_id}` | families table, map |
| `member.joined` | an invite is accepted, or a new head finishes setup | `{family_id, member: MemberOut}` | member lists, counts |
| `member.updated` | a role, avatar, name, or `location_sharing_allowed` changes | `{family_id, member: MemberOut}` | member lists, **map marker labels and badges** |
| `member.removed` | a member is removed | `{family_id, user_id}` | member lists, counts |

`family.updated` and `member.updated` are the events that make a policy change take effect
without a reload. When either arrives carrying a permission term that has become `false`, the
live-location layer removes that marker immediately rather than waiting for the next poll —
a marker that should no longer be visible must not linger for a refresh interval.

The reverse is not symmetrical: a permission term becoming `true` does **not** make a marker
appear, because the client has no location to draw. It appears on the sharer's next position
update, which is the only moment the product has a fresh coordinate to be honest about.

`member.updated` carries the coarse `MemberOut`, whose `location_sharing_enabled` is null for
recipients not entitled to it (see the schema above). A member's own consent state is
therefore never broadcast to the whole trip room.

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

> NOTE (implementation, Phase 9): shipped as a **card grid**, not a table, following the agreed
> mockup `design-preview/screen-families.html` and `plan/overview.md`'s UI-first rule ("feature
> UI work starts from the agreed mockup"). The mockup is right here: a trip has at most eight
> families of a few people each, so what is worth seeing at a glance is *who is in each
> family* — which a card holds and a row cannot. Tri-state sort over eight rows solves a
> problem this screen does not have. What survived from this paragraph is what mattered: the
> colour swatch is always paired with the name, the member count is tabular, density comes
> from spacing tokens, and the whole card is one click target.
>
> The **map half** of the map/table pair is deferred with the map shell (M2): there is no map
> component in the app yet, and `plan/architecture.md` reserves the browser Maps SDK for
> `map-suggestions`. The rule that mattered — "families without coordinates are not silently
> invisible" — is kept: every card states its home town, or "No home set", or "Not placed".
- **Selection:** clicking a row or a pin opens that family in the side panel. The panel holds
  the family header (colour swatch, name), the home block, the member list, the location
  block, and the invite block. Admin controls appear only for callers who are entitled to
  them, and the backend refuses regardless.
- **Member list rows:** avatar (or initials badge) at 32px, full name, role chip, and — for
  that family's head or spouse, the owner and organisers only — the per-member location switch described
  below. Every row's badge carries the family colour as its border, so a member is
  identifiable as belonging to this family even where the row is seen out of context.

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
  If the cause is `no_api_key` and the viewer is the owner or an organiser, the message links to the
  admin console's Google status section instead.

### Identity badge

The badge is one component, used at four sizes and in five places: map markers
(`holiday-stage`), member lists, the top-bar presence stack, comment authors, and the profile
page. Defining it once here is what stops the same person looking like two different people on
two screens.

- A circle. Avatar image when `avatar_thumb_url` is set; otherwise the `initials` string from
  `MemberOut`, centred, in the type ramp's smallest step scaled to the badge.
- A 2px ring in that member's `--family-N` token, always — image or initials. The ring is the
  family carrier; it is never the only carrier of anything, because a name label or hover
  always accompanies it (`plan/design-system.md`'s "colour is never the sole signal" rule).
- Initials fall back to a neutral surface fill, not the family colour, so the ring stays
  legible against it and contrast does not depend on which of the eight slots a family holds.
- Sizes: 24px (comment author), 32px (member list, presence stack), 40px (map marker), 64px
  (profile page). The image is requested at `avatar_thumb_url` for everything up to 40px and
  `avatar_url` at 64px.
- A missing or broken image URL renders the initials rather than a broken-image glyph. The
  badge has no failure state.

### Avatar upload

In the profile page. `Upload a photo` opens the file picker; the accepted formats and the 8MB
limit are stated next to the control before it is pressed, not only on error.

- After choosing, a square crop preview is shown with `Save` / `Choose another`. The crop is
  centre-square by default and is not adjustable in v1 — an image cropper is a component this
  product does not otherwise need.
- Saving shows an inline spinner on the button (a seconds-long wait, so a spinner rather than
  a skeleton). On success the badge updates everywhere the socket reaches.
- `Remove photo` reverts to the initials badge. It is reversible by uploading again, so it
  uses an undo toast rather than a confirm.
- Errors render inline beneath the control with the specific cause: format, size, or
  unreadable image. Never a generic "upload failed".

### Family location settings

A block in the family side panel, visible to every member of that family, **editable** only by
that family's head or spouse, the owner and organisers. Members see it read-only so they can understand why
their own toggle may be having no effect — a setting that silently overrides you, invisibly,
is the thing this block exists to prevent.

Two controls:

- **Show our family on the map** (`location_sharing_allowed`, default on). A switch. Its
  helper text names the consequence exactly: "When this is off, nobody in this family appears
  on the trip map, including you. It does not change anyone's own sharing setting — turning it
  back on restores whoever had chosen to share."
- **New members start with sharing on** (`member_location_default`, default off). A switch.
  Helper text: "This only sets what the toggle starts at for someone joining later. It does
  not change anyone already in the family, and everyone is still asked by their browser before
  any location is sent."

Then the per-member list, one row per member: badge, name, and a switch bound to
`family_members.location_sharing_allowed`. Each row shows the member's *effective* state as
text beneath the name, which is the only place the three inputs are visible together:

| Effective state | Row text |
|---|---|
| all three true, fresh row | "Sharing now" |
| all three true, no fresh row | "Sharing is on — not visible while the app is closed" |
| member has not consented | "Off — only they can turn this on" |
| this switch off | "You have turned this off for them" |
| family switch off | "Off for the whole family" |

The fourth and fifth rows are worded in the second person deliberately: the head or spouse is
looking at a consequence of their own action, and the copy should say so rather than reporting
a neutral state.

> NOTE (implementation, Phase 9): the first row is unreachable until `holiday-stage` ships —
> "sharing now" needs a fresh `live_locations` row, which that feature owns. Until then a
> member whose three permission terms all pass gets the second string, which is true either
> way and errs towards *not* claiming somebody is visible when the app cannot know. An
> indicator that over-promises here is worse than one that under-promises. A sixth string was
> needed and added: when the viewer is not entitled to a member's consent state at all
> (`location_sharing_enabled` is null), the row reads "Only they can see this setting" rather
> than inventing one of the five.

Turning the family switch off shows an undo toast rather than a confirm — it is instantly
reversible and restores exactly the previous set of sharers, so a confirm dialog would be
friction without a decision behind it.

### Invites

In the family side panel, an `Invite someone` action. A small form (expiry select, default
7 days) produces the link in a copy-once block: the URL, a `Copy link` button, the expiry, and
a plain line stating the link is shown only now and cannot be retrieved later. A toast confirms
the copy — a transient confirmation of the user's own action, which is exactly what toasts are
for.

Outstanding invites list below: created by, created, expires, status chip
(`active` / `used` / `expired` / `revoked`), and a `Revoke` action on active ones. Revoke is a
low-stakes reversible-by-reissue action, so it uses undo rather than a confirm dialog.

The owner's and organisers' family view also offers `Invite a new family`, which creates the
`family_id: null` variant. It sits visually apart from the per-family invite so the two are
not confused.

> REVISED 2026-08-11: this card previously carried a second action, `Or add one myself`, which
> opened a create-family dialog over the bare `POST /families`. Both are gone with the route
> (FM-1). The card is now the single answer to "how do I add a family", which is also the true
> one — a family arrives when its head accepts the link.

### Join / registration screen

A standalone route `/join/<token>` outside the app shell — no nav rail, no tabs, because the
visitor is not yet a member.

- Fetches the preview first and renders it before asking for anything: instance name, trip
  name, and either "You are joining the <name> family" or "You will create a new family".
- Invalid token: a single plain card — "This invite link is no longer valid" plus the reason
  in ordinary words and "Ask whoever invited you for a new link." No trip details.
- Valid: the form — first name, last name, username, password, confirm. All five field states
  styled; validate on blur; username-taken shows on that field. Last name is the one optional
  field, labelled as such rather than silently accepting an empty value.
- Neither display name nor family name is asked for here. Display name is derived from the two
  name fields and edited later on the profile page; family name is asked on the family setup
  screen that follows, for `create_family` invites only.
- Trip in the End stage: the preview says the trip has finished and the form is not shown.
- Already logged in: the preview is shown with an explanation that joining needs a separate
  account, and a `Log out and continue` action (FM-8).

### Family setup screen

Rendered whenever `auth/me` returns `next_step: "setup_family"` (foundation F-13) — which is
the state a new family's head is in from the moment they accept a `create_family` invite until
they have named their family, **and the state the owner is in between naming the trip and
entering the app** (added 2026-08-11). A standalone route `/setup/family`, outside the app
shell for the same reason the join screen is: they are not on the trip yet.

- Heading and one line of context: "Name your family — you can invite the rest of them next."
  The trip name is shown so it is obvious which trip this is for.
- The copy is written to be true for both callers and is therefore not branched on role. It
  never says "you were invited": the invited founder reads "Name your family / You can invite
  the rest of them next / This is for <trip>" and so does the owner, who has just named that
  trip on the previous screen. The one line that would have read oddly for the owner is the
  reassurance about who the family belongs to — "You will be this family's head. You can rename
  the family and hand that role on later" — and it reads correctly for both, because the owner
  is a head of their own family like anyone else. That is the point of the two role kinds being
  independent, so the screen that makes them one is the wrong place to start explaining it.
- One required field, family name, validated on blur. `409 name_taken` renders on that field
  with the message from the edge-case table, not as a toast.
- Optionally, the home address field from the side panel, presented as skippable with a plain
  "You can add this later" — it is not required to finish setup, and requiring a geocode to
  complete registration would make an external service a gate on getting into the app.
- Below the field, a short line stating what happens: "You will be this family's admin. You
  can rename the family and change who administers it later."
- `Create family` submits `POST /families/mine`. On success `next_step` becomes `app` and the
  shell routes to home; the user is now a member and every other route opens up.
- Abandoning the screen changes nothing: `next_step` is derived from stored state, so the next
  login lands here again. There is no partial family row to clean up, because nothing is
  written until submit.
- Because this screen is the only thing a `setup_family` user can reach, it carries its own
  log-out action; the nav rail that normally holds one is not rendered.

> NOTE: the trip-level equivalent of this screen — the owner's first-login trip setup —
> is **not** specified here. It belongs to `admin-console` (AC-0), which owns every write to
> `trips`. Both screens are reached through the same `next_step` gate, and that gate is
> foundation's (F-13); only the two destination screens are owned by different features.

### Profile page

One page reached from the nav rail. Available in every stage, including End.

- Profile picture: current avatar (or the initials badge that stands in for it), with
  `Upload a photo` / `Remove photo`. Upload rules and states are in the avatar section below.
- First name and last name: inline edit, save on blur with an undo toast. Changing either
  updates the initials badge and every map marker label live.
- Display name: inline edit, save on blur with an undo toast. Seeded from
  `"{first_name} {last_name}"` at registration and editable afterwards, so a member who goes
  by something other than their legal name can say so without breaking the initials.
- Password change (foundation's form) and theme control (foundation's control).
- My location sharing: the member's own toggle, with the settings copy from
  `plan/features/holiday-stage/design.md`. When the family's policy currently blocks sharing,
  the toggle is shown with an explanation of who to ask rather than hidden — see FM-15.
- A read-only block showing username, family and role.

### Empty states

- No families: "No families yet — invite the first one" with the new-family invite action
  inline (owner or organiser); members see "The trip organiser hasn't added any families yet."
  On a fresh install the owner never sees this state, because their own family setup (FM-13)
  happens before they can reach the screen — so the empty state is genuinely about *other*
  families, which is what the invite action offers.
- Family with one member: no special state, but the invite action is given prominence.
- No outstanding invites: "No open invites."

### Loading

Skeletons for the families table and the side panel structure; spinners for the inline
save/geocode waits. Optimistic updates for rename and colour change, rolled back if the
request fails.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| 25th family created (all 24 slots taken) | Refused to take a slot; the picker offers the colour wheel instead. Submitting `color` while exhausted still gets `409 no_color_slots` if no wheel value is given |
| Colour slot taken | `409` code `color_taken`, message names the holding family |
| Custom colour submitted while a slot is still free | `422` code `custom_color_not_allowed` — the wheel only opens on the 25th family |
| Both `color` and `color_custom` submitted together | `422` code `invalid_color_choice` — exactly one is accepted, mirroring the DB's XOR constraint |
| Duplicate family name on the trip | `409` code `name_taken` |
| Delete a family with members | `409` code `family_not_empty`; the message says to remove members first |
| Remove or demote the head of family | `409` code `head_required`; the message says to transfer the role first. A family always has exactly one head |
| Transfer the head role | `PATCH .../members/{id}` with `role: "head"`. One transaction: the incoming head becomes `head` and the outgoing one becomes `spouse` |
| Spouse tries to remove, demote or switch off the head | `403` code `head_protected`; the UI never showed the control |
| Spouse tries to change **any** role, including taking `head` themselves | `403` code `spouse_cannot_promote`. A separate rule from the one above, with a separate code: that one protects the head *as a target*, this one keeps the composition of the family's leadership in the head's hands whoever the target is. Taking `head` would demote the incumbent by a side door |
| Remove or demote the trip's owner | `403` code `owner_protected` |
| A head or spouse acts on another family | `403 forbidden`; the UI never showed the control |
| An organiser tries to appoint or remove an organiser | `403` code `owner_only` (route lives in `admin-console`) |
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
| `create_family` acceptor abandons setup and logs back in | `auth/me` returns `setup_family` again and they land on the same screen. Nothing was written on the first visit, so there is nothing stale to reconcile |
| `create_family` acceptor calls any other route before finishing setup | `403 not_on_trip` from `require_member`. The shell never routes them anywhere that would issue such a call |
| `POST /families/mine` submitted twice (double-tap, retry after timeout) | The second gets `409 already_has_family`; the client treats it as success and re-reads `auth/me` |
| `POST /families/mine` by a user who already has a family | `403 forbidden` from `require_pending_family`; there is no path to a second family |
| The owner, with no family, on a fresh install | `next_step` is `setup_trip` until the trip is named, then `setup_family`. They finish on the same screen an invited founder uses and become the head of their own family (2026-08-11) |
| The owner calls `POST /families/mine` a second time | `403 forbidden` — they now have a family, and the owner's admission to the route is conditional on not having one. Ownership is not a standing licence to found families |
| Anything calls `POST /families` | `405 method_not_allowed` — the route is gone (2026-08-11). `GET /families` still answers there, so the path is not free for a new meaning |
| `POST /families/mine` when all 24 colour slots are taken and no `color_custom` was given | `409 no_color_slots`. The client should not reach this — the picker switches to the colour wheel once `GET /families/palette` reports `exhausted: true` — so this is the API's own backstop, not the primary UX |
| A head or spouse turns the family switch off while a member is actively sharing | `family.updated` removes every marker for that family immediately. The member's own toggle stays on and their persistent "Sharing your location" indicator changes to say the family's setting is currently hiding them — the indicator must never claim they are visible when they are not |
| A head or spouse turns the per-member switch off for someone actively sharing | Same, for that one marker |
| A head or spouse sets `member_location_default` on | No existing member changes. Only `family_members` rows created afterwards are seeded from it |
| A seeded-on member opens the app for the first time | The one-time disclosure appears before any `watchPosition` call. `Not now` writes their own `false`; the family default is not consulted again |
| Member turns their own sharing on while the family switch is off | Allowed and stored. They see "On — your family's settings are hiding you for now" with a pointer to their head of family. Refusing the write would mean the head's switch had silently overwritten a personal setting |
| An owner or organiser changes another family's location policy | Allowed — they manage any family (FM-10). The change is attributed in the `member.updated` payload so it is not mistaken for the family's own action |
| Member removed from a family while their per-member switch is off | The `family_members` row is deleted and the switch goes with it. Re-inviting them starts from the family's current default, not from the old value |
| Avatar uploaded with a non-image file renamed to `.jpg` | `415 unsupported_media_type` — the type comes from magic bytes, not the extension |
| Avatar upload larger than 8MB | `413 file_too_large`; the limit was stated before the picker opened |
| Avatar image is corrupt, or a decompression bomb | `422 image_unreadable`; decoding is bounded so the container is never exhausted |
| Avatar replaced | Old file and `attachments` row are deleted in the same transaction as the new one is written; the URL changes because it is content-hashed, so no cache needs invalidating |
| User with an avatar is removed from the trip | The avatar survives with the user record, as their votes and comments do. Their badge still renders correctly on historical content |
| Member has a single-word name (`last_name` empty) | One-letter badge, full name label is just the first name. Not an error state |
| Two members of one family share initials | Expected and not disambiguated on the badge. The hover label and the member list carry the full name, which is where the distinction belongs |
| A user is removed while they have the app open | Their socket gets `member.removed`; the client refetches `auth/me` and shows a "you are no longer on this trip" screen rather than erroring |
| Colour changed while another user views the map | `family.updated` repaints pins live |
| Stage becomes `end` mid-edit | The save returns `409 stage_forbidden`; the UI shows the archive banner and switches to read-only |
| Geocode succeeds but the family is deleted meanwhile | The write is a no-op; no error surfaced |

## Dependencies and hand-offs

- **Depends on `foundation`** for sessions, CSRF, `require_member` /
  `require_family_head_or_spouse` / `require_organiser` / `require_owner` / `require_stage`, the error envelope, the
  WebSocket broadcast helpers, the password endpoint, and the `next_step` onboarding gate
  (F-13) that routes to the family setup screen.
- **Provides to `distances`** the geocoded `home_lat`/`home_lng` that Distance Matrix pairs are
  computed from. That feature must treat a null home as "no distances available", not as an
  error.
- **Provides to `admin-console`** the family and member listing used by its overview section.
  Account-level operations (reset password, delete user) live there, not here.
  `admin-console` owns the *trip* setup screen (AC-0); this feature owns the *family* one.
  They share only foundation's gate.
- **Provides to every map feature** the `--family-N` colour slot used for pins and labels, and
  the identity badge component (avatar, initials, family ring) defined under UI behaviour.
- **Provides to `holiday-stage`** the three permission terms of the location-visibility rule
  and the `initials` / `avatar_thumb_url` fields its markers render. That feature must compute
  visibility from those terms rather than from `user_settings` alone, and must not offer any
  control that writes them — the settings live here.
