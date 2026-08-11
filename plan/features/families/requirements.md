# families — Requirements

**Milestone:** M1. **Reads first:** `plan/overview.md`, `plan/architecture.md`,
`plan/design-system.md`, `CLAUDE.md`, and `plan/features/foundation/`.

A trip is made of families, not loose individuals. Every member belongs to exactly one
family; each family has a colour slot used for pins and labels across the whole product, and
one home address that is geocoded once so home-to-suggestion distances can be cached later.
People join by invite link — either into an existing family, or by creating a new family.

## User stories

### FM-1 — Main admin: create a family

**As the main admin, I can create a family so I can invite its members.**

- Required: name. Optional at creation: home address.
- A colour slot from `--family-1…8` is assigned automatically, choosing the lowest-numbered
  slot not currently in use on the trip.
- The main admin can override the colour slot; slots already used by another family are shown
  as taken.
- The family is created on the active trip (`families.trip_id`).
- A family name that duplicates an existing name on the trip is rejected with a clear message.

### FM-2 — Family admin: edit my family's name and colour

**As a family admin, I can rename my own family and change its colour slot.**

- A family admin can edit only their own family; the main admin can edit any.
- Changing the colour slot to one already taken is rejected with a message naming the family
  holding it.
- The change is reflected immediately on the map and in any list showing family colours, for
  every connected user.

### FM-3 — Family admin: set our home address

**As a family admin, I can set our home address so the app can show us how far things are.**

- The address is entered as free text and stored in `families.home_address`.
- On save the server geocodes it **once**, writing `home_lat`, `home_lng` and
  `home_geocoded_at`.
- The resolved address and a small map preview are shown back for confirmation before the
  value is committed.
- If geocoding returns no result, the address is still saved, coordinates stay null, and the
  family sees a clear "we could not place this address" state with a retry action.
- If geocoding is unavailable (no server key configured, or the API is failing), the address
  saves and a "not yet placed" state appears; a retry action re-attempts later.
- Editing the address to a different value clears the old coordinates and re-geocodes.
  Re-saving an unchanged address does **not** call the API again.
- Only a family admin (own family) or the main admin may set it.

### FM-4 — Any member: see the families on this trip

**As a member, I can see every family on the trip, their colour, and who is in them.**

- A table lists families with: colour swatch, name, member count, home town or "no home set",
  and whether the home is placed on the map.
- Full home addresses are visible to members of that family and to the main admin. Other
  members see a coarse label only (the town/locality from the geocode result), never the full
  street address.
- Selecting a family opens its detail panel with its member list.
- Homes with coordinates appear on the map as family-coloured home pins.

### FM-5 — Family admin: invite someone to my family

**As a family admin, I can create an invite link that adds someone to my family.**

- Creating an invite produces a single-use link containing an unguessable token.
- The creator chooses an expiry from a short list (24 hours, 7 days, 30 days); default 7 days.
- The link is displayed once with a copy action, along with its expiry and who created it.
- The invite is scoped to the creator's family (`invites.family_id` set).
- A family admin sees all outstanding invites for their own family and can revoke any of
  them.
- A revoked or used invite cannot be used again.

### FM-6 — Main admin: invite someone who will start a new family

**As the main admin, I can create an invite that lets the recipient create their own family.**

- The invite is created with `invites.family_id` null, which means "this invite creates a new
  family".
- Only the main admin can create this variant. A family admin can only invite into their own
  family.
- On acceptance the recipient is logged in and directed to the family setup screen (see
  `plan/features/families/design.md` "Family setup screen") where they name their new family,
  become its family admin automatically, and may set a home address then or later.

### FM-7 — Logged-out visitor: accept an invite and register

**As someone holding an invite link, I can create my account and join the trip.**

- Opening the link shows a preview before any details are entered: the instance name, the trip
  name, and either the family being joined or "you will create a new family".
- The registration form asks for a first name, a last name, a username and a password (same
  password rules as foundation: no minimum length, confirmation must match). Last name is
  optional and labelled as such; everything else is required.
- No display name is asked for. It is set to "first last" and can be changed later on the
  profile page (FM-11), so nobody meets three name fields before they have seen the app.
- A username already taken is rejected with a clear, specific message on that field.
- On success the account is created, the invite is marked used (`invites.used_by`), the user is
  logged in, and what happens next depends on the invite's mode:
  - **`join`** — the `family_members` row is written with `role = 'member'`, their location
    setting is seeded from that family's default (FM-15), and they land on the app home.
  - **`create_family`** — **no family membership is written**, because no family exists yet.
    They land on the family setup screen (FM-13), and are not a member of the trip until they
    finish it.
- An expired, revoked, already-used or unknown token shows a plain explanation and an
  instruction to ask the person who invited them for a new link. No detail about the trip or
  its families is revealed for an invalid token.
- Registration is possible **only** through a valid invite. There is no open sign-up form in
  v1, regardless of the `registration_open` setting.

> NOTE: `plan/architecture.md` includes a `registration_open` setting and `admin-console`
> exposes a registration/invite policy. In v1 the only implemented policy is invite-only; the
> setting exists so the policy can be widened later without a migration. The admin console
> shows it as such.

### FM-8 — Logged-in user: accept an invite for a second account

**As a logged-in user opening an invite link, I am told what will happen rather than silently
switching accounts.**

- The preview explains that accepting requires a separate account and offers to log out first.
- A user who already belongs to a family cannot accept an invite into a different family
  without being removed from the first — the app says so rather than failing obscurely.

### FM-9 — Family admin: manage my family's members

**As a family admin, I can manage the people in my own family.**

- I can see each member's display name, username, role and when they joined.
- I can promote a member to family admin, and demote a family admin to member.
- I can remove a member from the family.
- I cannot remove myself while I am the only family admin; the app asks me to promote someone
  else first.
- I cannot remove or demote the main admin.
- A removed member's account still exists but has no family, so they lose member access until
  they are re-invited. Their past votes, comments and suggestions are retained and still
  attributed to them.

### FM-10 — Main admin: manage any family

**As the main admin, I can do anything a family admin can do, for any family.**

- Includes creating, renaming, recolouring, setting the home address, inviting, and managing
  members and roles for every family.
- The main admin can also delete a family that has no members.
- Deleting a family with members is refused; members must be removed first. This is
  deliberate — it prevents accidental loss of a whole group's access.
- Removing users entirely and resetting passwords belong to `admin-console`, not here.

### FM-11 — Any user: manage my own profile

**As a logged-in user, I can change my name, my picture and my password.**

- First name, last name and display name are each editable by the user at any time, in any
  stage. Changing a name updates my initials badge and my map label everywhere, live.
- My profile picture is uploaded and removed here (FM-14).
- My own location-sharing toggle lives here too, alongside the explanation of what it does
  (`plan/features/holiday-stage/`, HS-9). If my family's settings are currently hiding me, the
  toggle still works and says so — it is never silently disabled by someone else's decision.
- Password change reuses foundation's endpoint and rules; changing it revokes my other
  sessions.
- Username is not editable in v1.
- Theme preference is edited here too, reusing foundation's preferences endpoint, so profile
  is one coherent page.

### FM-12 — Any member: see changes without reloading

**As a member, family and membership changes appear without me refreshing.**

- When a family is renamed or recoloured, open views update.
- When someone joins or is removed, member lists and counts update.
- When a home address is geocoded, the home pin appears on the map.
- When someone changes their picture or name, their badge and map label update.
- When a family's location settings change, markers that are no longer permitted disappear
  immediately, without waiting for a refresh.

### FM-13 — New family admin: name my family on first login

**As someone who accepted an invite to start a new family, I am asked to name my family before
I enter the app.**

- After registering I am logged in and taken straight to a family setup screen. I am not yet on
  the trip: I have an account, but no family.
- The screen asks for one thing — our family name — and optionally lets me add our home
  address, clearly marked as something I can do later.
- It tells me I will be this family's admin, and that the name and the admin can both be
  changed afterwards.
- A name already used on this trip is rejected on the field with a specific message.
- On submit, my family is created, I become its admin, a colour is assigned automatically, and
  I land on the app home.
- If I close the tab without finishing, nothing is half-created; logging in again brings me
  back to the same screen.
- Until I finish, no other part of the app is reachable — not because the UI hides it, but
  because I am genuinely not on the trip yet and the server refuses.

> NOTE: this splits what would otherwise be one long registration form into two screens. The
> reason is that the two questions have different owners in time: who you are is answered by
> the person holding the link, at the moment they click it; what your family is called is often
> agreed with the rest of the family first. A resumable second screen lets that happen without
> the invite going stale.

### FM-14 — Any user: put a face to my name

**As a member, I can upload a profile picture, and I am recognisable on the map without one.**

- I can upload a JPEG, PNG or WebP up to 8MB from the profile page, see a square preview, and
  save it.
- The picture is resized and re-encoded server-side; the original is not kept.
- **All metadata is stripped, including any GPS coordinates the photo was taken with.** A
  product built around a location-privacy promise must not republish a location hidden in a
  photo.
- I can remove my picture at any time and go back to initials.
- With no picture I get an initials badge — the first letter of my first name and the first
  letter of my last name. With a single name, one letter.
- Either way the badge carries my family's colour as a ring, and my full name is always
  available as a label or on hover, so colour is never the only thing identifying me.
- My picture is visible to everyone on the trip and to nobody else.

### FM-15 — Family admin: decide who in my family appears on the map

**As a family admin, I can control which of my family are shown on the trip map, without being
able to switch on sharing for someone who has not agreed to it.**

- Everyone on the trip is shown on the map individually — one marker per person, not one per
  family.
- I have a single switch for my whole family: *show our family on the map*. It is on by
  default. Turning it off removes every one of us from the map, myself included, and does not
  change anybody's own setting — turning it back on restores exactly the people who had chosen
  to share.
- I have a switch per member, so I can show some of my family and not others.
- I set the default that new members start with. It is off by default. It applies only to
  people who join after I set it; it never rewrites the setting of someone already here.
- My own sharing is on from the moment I create the family, because the person organising a
  family's travel is the one the rest of them expect to be able to find.
- **None of my controls can turn on sharing for another person.** They can only prevent it.
  A member's own toggle, and their browser's own permission prompt, are still required — and
  only they can answer either.
- A member whose sharing I have turned off is told so plainly in their own settings, with who
  to ask. It is never silently ineffective.
- The main admin can do all of this for any family, as they can with everything else (FM-10).

> NOTE: this is a real change to the rule in `plan/features/holiday-stage/requirements.md`
> that said sharing was governed by the member alone. The invariant that survives — and the
> one that matters — is that **permission and consent are separate, and an admin holds only
> permission**. Seeding a new member's default is the single point where an admin's decision
> touches a member's own setting, it happens once, and the browser's permission prompt still
> stands between it and any location leaving the device.

## Permissions

"Own" means the family the user belongs to.

| Action | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| List families and member counts | yes | yes | yes | no |
| See a family's full home address | yes (any) | own only | own only | no |
| See a family's coarse home locality | yes | yes | yes | no |
| Create a family for someone else | yes | no | no | no |
| Create my own family during setup | n/a | n/a (this is how you become one) | no | no |
| Rename / recolour a family | yes (any) | own only | no | no |
| Set or clear a home address | yes (any) | own only | no | no |
| Retry geocoding | yes (any) | own only | no | no |
| Delete an empty family | yes | no | no | no |
| Create a family-scoped invite | yes (any family) | own family only | no | no |
| Create a new-family invite | yes | no | no | no |
| List / revoke invites | yes (all) | own family only | no | no |
| Preview an invite by token | yes | yes | yes | yes |
| Accept an invite (register) | n/a | n/a | n/a | yes |
| Promote / demote a family admin | yes (any) | own family only | no | no |
| Remove a member from a family | yes (any) | own family only | no | no |
| Set a family's map-visibility switch | yes (any) | own only | no | no |
| Set a member's map-visibility switch | yes (any) | own family only | no | no |
| Set a family's new-member default | yes (any) | own only | no | no |
| Turn **on** another user's sharing | **no** | **no** | **no** | **no** |
| Edit own names / picture / password / theme | yes | yes | yes | no |
| Edit own location-sharing toggle | yes | yes | yes | no |
| Edit another user's names or picture | no (see `admin-console`) | no | no | no |

The main admin can never be removed from their family or demoted through this feature.

"Create my own family during setup" is available to exactly one caller: an authenticated user
who has accepted a new-family invite and has no family yet. It is not a general capability of
any role, which is why it does not fit the columns above.

The "turn on another user's sharing" row is `no` in every column on purpose. It is the one
capability this feature deliberately gives to nobody, and it is listed rather than omitted so
that a later reader can see it was a decision.

## Stage availability

| Capability | Planning | Holiday | End |
|---|---|---|---|
| View families, members, home pins | yes | yes | yes (read-only) |
| Create / edit / delete a family | yes | yes | no (`409`) |
| Create my own family during setup | yes | yes | no — an End-stage invite is refused before this point |
| Set or retry a home address | yes | yes | no (`409`) |
| Create / revoke invites | yes | yes | no (`409`) |
| Accept an invite | yes | yes | no — the trip is closed; the preview says so |
| Promote / demote / remove members | yes | yes | no (`409`) |
| Edit family / member map-visibility switches | yes | yes | no (`409`) |
| Edit own names, picture, password, theme | yes | yes | yes |
| Edit own location-sharing toggle | yes | yes | yes |

Account operations stay available in End because they are not trip data — consistent with
foundation. Everything else is frozen.

The location-sharing toggle stays editable in End even though there is nothing to share: it is
a personal setting, and the one direction that matters — turning it off — must never be blocked
by the trip's state. `holiday-stage` separately purges all live-location rows on entering End,
so an End-stage toggle has no effect on the map either way.

Family and member visibility switches are frozen in End along with the rest of the trip record,
because by then they describe a finished trip rather than governing anything live.

## Out of scope

- Removing a user account entirely, and admin password resets — `admin-console`.
- Instance settings and registration policy editing — `admin-console`.
- Home-to-suggestion driving distances — `distances`. This feature only produces the geocoded
  home coordinates that feature depends on.
- Places Autocomplete on the address field. v1 uses free text plus a server-side geocode; the
  browser Places SDK is reserved for the create-suggestion flow per `plan/architecture.md`.
- Multiple homes per family, or per-member addresses.
- Moving a member between families in one action; v1 removes then re-invites.
- Editing a profile picture in the browser beyond the automatic square crop — no zoom, pan or
  rotate. An image cropper is a component the product needs nowhere else.
- Per-member location scheduling ("share only between 9am and 6pm") or per-viewer visibility
  ("show me to my family but not to the Smiths"). The switches are all-or-nothing per person.
- Email delivery of invites. Links are copied and shared by whatever channel the family
  already uses; v1 has no mail transport.
- More than eight families. The colour palette defines eight slots; a ninth family is refused
  with a clear message rather than silently reusing a colour.
