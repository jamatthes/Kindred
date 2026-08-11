# families — Requirements

**Milestone:** M1. **Reads first:** `plan/overview.md`, `plan/architecture.md`,
`plan/design-system.md`, `CLAUDE.md`, and `plan/features/foundation/`.

A trip is made of families, not loose individuals. Every member belongs to exactly one
family; each family has a colour slot used for pins and labels across the whole product, and
one home address that is geocoded once so home-to-suggestion distances can be cached later.
People join by invite link — either into an existing family, or by creating a new family.

## Roles (revised 2026-08-11)

This feature owns the role hierarchy; `plan/overview.md` states it and `admin-console` and
`holiday-stage` inherit it. Two independent kinds:

| Kind | Role | Scope |
|---|---|---|
| Trip | **Owner** | `trips.owner_user_id`. Everything an organiser can do, plus appointing and removing organisers — which is theirs alone |
| Trip | **Organiser** | A `trip_organisers` row. Every cross-family power except managing organisers |
| Family | **Head of family** | One per family. Manages their own family entirely |
| Family | **Spouse** | The head's powers over the family, **except over the head themselves** |
| Family | **Member** | Belongs to one family; decides their own location sharing and nothing else |

The two kinds do not imply each other: the owner and every organiser are also an ordinary
head, spouse or member of their own family, and hold no family powers elsewhere except the
cross-family ones their trip role gives them.

**The two asymmetries, and why each exists:**

- *An organiser cannot appoint or remove an organiser.* A delegate who can unappoint the
  delegator is not a delegate. Without this, the owner's control of who runs the trip lasts
  until the first organiser disagrees, and there is no way back.
- *A spouse cannot modify, demote or remove the head, or change the head's visibility
  switches.* Two people who can each remove the other is a family that can lock itself out in
  one click. The relationship is one-directional: the head can do all of those to a spouse.

Where a story below says "head or spouse", the spouse asymmetry applies whenever the **target**
of the action is the head. It is a property of the action, not of the role — a spouse may edit
every other member of the family freely.

> This replaces the earlier vocabulary. "Main admin" is now **owner or organiser** wherever it
> appears in a permission (`require_organiser`); the small number of powers reserved to the
> owner alone are called out explicitly. "Family admin" is now **head of family**.

## User stories

### FM-1 — Owner or organiser: create a family

**As the owner or an organiser, I can create a family so I can invite its members.**

- Required: name. Optional at creation: home address.
- A colour slot from `--family-1…8` is assigned automatically, choosing the lowest-numbered
  slot not currently in use on the trip.
- The creator can override the colour slot; slots already used by another family are shown
  as taken.
- The family is created on the active trip (`families.trip_id`).
- A family name that duplicates an existing name on the trip is rejected with a clear message.

### FM-2 — Head or spouse: edit my family's name and colour

**As a head of family or a spouse, I can rename my own family and change its colour slot.**

- A head or spouse can edit only their own family; the owner and organisers can edit any.
- Changing the colour slot to one already taken is rejected with a message naming the family
  holding it.
- The change is reflected immediately on the map and in any list showing family colours, for
  every connected user.

### FM-3 — Head or spouse: set our home address

**As a head of family or a spouse, I can set our home address so the app can show us how far things are.**

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
- Only the head or a spouse (own family), the owner, or an organiser may set it.

### FM-4 — Any member: see the families on this trip

**As a member, I can see every family on the trip, their colour, and who is in them.**

- A table lists families with: colour swatch, name, member count, home town or "no home set",
  and whether the home is placed on the map.
- Full home addresses are visible to members of that family and to the owner and organisers. Other
  members see a coarse label only (the town/locality from the geocode result), never the full
  street address.
- Selecting a family opens its detail panel with its member list.
- Homes with coordinates appear on the map as family-coloured home pins.

### FM-5 — Head or spouse: invite someone to my family

**As a head of family or a spouse, I can create an invite link that adds someone to my family.**

- Creating an invite produces a single-use link containing an unguessable token.
- The creator chooses an expiry from a short list (24 hours, 7 days, 30 days); default 7 days.
- The link is displayed once with a copy action, along with its expiry and who created it.
- The invite is scoped to the creator's family (`invites.family_id` set).
- A head or spouse sees all outstanding invites for their own family and can revoke any of
  them.
- A revoked or used invite cannot be used again.

### FM-6 — Owner or organiser: invite someone who will start a new family

**As the owner or an organiser, I can create an invite that lets the recipient create their own family.**

- The invite is created with `invites.family_id` null, which means "this invite creates a new
  family".
- Only the owner or an organiser can create this variant. A head or spouse can only invite
  into their own family.
- On acceptance the recipient is logged in and directed to the family setup screen (see
  `plan/features/families/design.md` "Family setup screen") where they name their new family,
  become its head of family automatically, and may set a home address then or later.

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

### FM-9 — Head or spouse: manage my family's members

**As a head of family or a spouse, I can manage the people in my own family.**

- I can see each member's display name, username, role and when they joined.
- I can promote a member to **spouse**, and demote a spouse back to member (FM-16).
- I can remove a member from the family.
- **A family always has exactly one head.** I cannot remove or demote the head; handing the
  role on is a transfer, not a vacancy (FM-16).
- I cannot remove or demote the trip's owner.
- **As a spouse, everything above applies except where the head is the target**: I cannot
  remove the head, change their role, or change their visibility switches. The app does not
  offer those controls, and the API refuses them.
- A removed member's account still exists but has no family, so they lose member access until
  they are re-invited. Their past votes, comments and suggestions are retained and still
  attributed to them.

### FM-10 — Owner or organiser: manage any family

**As the owner or an organiser, I can do anything a head of family can do, for any family.**

- Includes creating, renaming, recolouring, setting the home address, inviting, and managing
  members and roles for every family.
- The owner and organisers can also delete a family that has no members.
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

### FM-13 — New head of family: name my family on first login

**As someone who accepted an invite to start a new family, I am asked to name my family before
I enter the app.**

- After registering I am logged in and taken straight to a family setup screen. I am not yet on
  the trip: I have an account, but no family.
- The screen asks for one thing — our family name — and optionally lets me add our home
  address, clearly marked as something I can do later.
- It tells me I will be this family's head, and that the name and the head can both be
  changed afterwards.
- A name already used on this trip is rejected on the field with a specific message.
- On submit, my family is created, I become its head, a colour is assigned automatically, and
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

### FM-15 — Head or spouse: decide who in my family appears on the map

**As a head of family or a spouse, I can control which of my family are shown on the trip map,
without being able to switch on sharing for someone who has not agreed to it.**

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
- The owner and organisers can do all of this for any family, as they can with everything
  else (FM-10). A spouse can do it for every member of their family except the head.

> NOTE: this is a real change to the rule in `plan/features/holiday-stage/requirements.md`
> that said sharing was governed by the member alone. The invariant that survives — and the
> one that matters — is that **permission and consent are separate, and an admin holds only
> permission**. Seeding a new member's default is the single point where an admin's decision
> touches a member's own setting, it happens once, and the browser's permission prompt still
> stands between it and any location leaving the device.

### FM-16 — Head of family: share the running of my family with my spouse

**As a head of family, I can give another adult in my family the same powers I have, without
giving them power over me.**

- I can promote any member of my family to **spouse**, and demote a spouse back to member.
- A spouse can do everything I can do for this family: manage members, set the home address,
  create and revoke invites, and set the family's and members' map-visibility switches.
- **A spouse cannot act on me.** They cannot remove me, change my role, or change my
  visibility switches. The controls are not rendered for them, and the API refuses the request
  regardless — the UI hiding a control is a courtesy, not a permission.
- A spouse cannot promote or demote anyone to or from spouse either. Promotion is mine, the
  owner's, or an organiser's. Otherwise a spouse could promote a confederate and outvote the
  arrangement I made.
- There is no limit on how many spouses a family has. A household with three adults sharing
  the arrangements is a real household, and an arbitrary cap would only be a rule to explain.
- **A family always has exactly one head.** I cannot demote myself and leave the family
  headless; I hand the role on instead, which makes me a spouse in the same action. That is a
  transfer, and the app describes it as one rather than as two half-completed steps.
- The owner and organisers can do all of this for any family (FM-10).

> NOTE: spouse is a permission level, not a claim about anyone's relationship. The name is the
> one families will read correctly in the overwhelmingly common case; nothing in the software
> checks or records a relationship, and any adult a head trusts with the arrangements can hold
> it. It is deliberately *not* called "family admin (second)" — the product is for families,
> and a label that describes the household reads better than one that describes the ACL.

### FM-17 — Owner: choose who helps me run the trip

**As the owner, I can appoint organisers to share the work of running the trip, and take that
back.**

- An organiser gets every cross-family power I have: confirming suggestions, moving stages,
  configuring voting modes, managing any family, and inviting anyone anywhere.
- **An organiser cannot appoint or remove an organiser — including themselves and each
  other.** That power is mine alone. Otherwise my choice of who runs the trip lasts only until
  the first organiser disagrees with it, and there is no way back.
- Being an organiser says nothing about my family or theirs: organisers are still an ordinary
  head, spouse or member of their own family, and the two roles are edited in different places.
- Removing an organiser takes the trip-level powers away and leaves their family membership,
  their votes and their comments untouched.

> The **endpoints and UI** for appointing organisers belong to `admin-console`, not here. This
> feature defines the role, creates the `trip_organisers` table, and honours it in every
> permission check and serialiser — so `admin-console` adds screens over a hierarchy that
> already works, rather than introducing one.

## Permissions

"Own" means the family the user belongs to. Trip roles and family roles are independent, so a
person's effective permission is the union of their row in each half of the table.

| Action | Owner | Organiser | Head | Spouse | Member | Logged-out |
|---|---|---|---|---|---|---|
| List families and member counts | yes | yes | yes | yes | yes | no |
| See a family's full home address | yes (any) | yes (any) | own only | own only | own only | no |
| See a family's coarse home locality | yes | yes | yes | yes | yes | no |
| Create a family for someone else | yes | yes | no | no | no | no |
| Create my own family during setup | n/a | n/a | n/a (this is how you become one) | no | no | no |
| Rename / recolour a family | yes (any) | yes (any) | own only | own only | no | no |
| Set or clear a home address | yes (any) | yes (any) | own only | own only | no | no |
| Retry geocoding | yes (any) | yes (any) | own only | own only | no | no |
| Delete an empty family | yes | yes | no | no | no | no |
| Create a family-scoped invite | yes (any family) | yes (any family) | own family only | own family only | no | no |
| Create a new-family invite | yes | yes | no | no | no | no |
| List / revoke invites | yes (all) | yes (all) | own family only | own family only | no | no |
| Preview an invite by token | yes | yes | yes | yes | yes | yes |
| Accept an invite (register) | n/a | n/a | n/a | n/a | n/a | yes |
| Promote a member to spouse | yes (any) | yes (any) | own family only | **no** | no | no |
| Demote a spouse to member | yes (any) | yes (any) | own family only | **no** | no | no |
| Transfer the head of family role | yes (any) | yes (any) | own family only | **no** | no | no |
| Remove a member from a family | yes (any) | yes (any) | own family only | own family, **not the head** | no | no |
| Set a family's map-visibility switch | yes (any) | yes (any) | own only | own only | no | no |
| Set a member's map-visibility switch | yes (any) | yes (any) | own family only | own family, **not the head** | no | no |
| Set a family's new-member default | yes (any) | yes (any) | own only | own only | no | no |
| **Appoint or remove an organiser** | **yes** | **no** | no | no | no | no |
| Turn **on** another user's sharing | **no** | **no** | **no** | **no** | **no** | **no** |
| Edit own names / picture / password / theme | yes | yes | yes | yes | yes | no |
| Edit own location-sharing toggle | yes | yes | yes | yes | yes | no |
| Edit another user's names or picture | no (see `admin-console`) | no | no | no | no | no |

The trip's owner can never be removed from their family or demoted through this feature.

The "appoint or remove an organiser" row is `yes` for the owner and `no` for everybody else,
including organisers themselves. The *endpoints* for it live in `admin-console`; the row is
here because this feature defines the hierarchy and creates the table those endpoints write.

The three `no` cells marked for spouse are the whole of the spouse asymmetry. A spouse who
could hand themselves the head role, or remove the head, would make the distinction
decorative.

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
| Promote / demote / remove members, transfer the head role | yes | yes | no (`409`) |
| Appoint / remove an organiser (`admin-console`) | yes | yes | no (`409`) |
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
