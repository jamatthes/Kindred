# map-suggestions — Requirements

Feature 5 in `plan/overview.md`. Milestone M3.

The core surface of Kindred. A Google Maps JS map sits center-stage; every suggestion a
family makes — a rough candidate *region*, an *accommodation*, an *activity*, or a *meal* —
is a record that renders both as a pin/overlay on that map and as a row in a list panel.
Map and list are two views of one dataset.

## Concepts

- **Suggestion** — one proposed thing. Type is one of `region` / `accommodation` /
  `activity` / `meal`. Status flows `proposed → shortlisted → approved → scheduled`, with
  `rejected` as a terminal side exit.
- **Region** — a drawn circle or rough polygon marking a candidate *area*, used early when
  no accommodation exists yet ("somewhere around here").
- **Author** — the user who created the suggestion. Their family supplies the pin's colour
  accent.

## User stories

### S1 — See everything on the map
**As a member, I can open the trip map and see every suggestion for the trip.**
- Pins are drawn for suggestions with `lat`/`lng`; regions draw as translucent shapes.
- Pin icon is determined by suggestion type; pin colour accent is the author's family colour.
- Overlapping pins cluster; expanding a cluster reveals the individual pins.
- Empty trip shows an empty state with the create action inline ("No suggestions yet —
  drop the first pin") in the list drawer; the map itself stays uncovered.
- The map fills the content area (revised 2026-08-12): search, filters, list, detail and the
  create form are summoned over it, never permanently docked beside it. See `design.md` >
  "Layout (revised 2026-08-12 — map-first)".

### S2 — See the same data as a list
**As a member, I can switch to (or open alongside) a list view of the same suggestions.**
- The list shows title, type, status, author family, vote tally, comment count, distance chip.
- Sorting is tri-state (asc → desc → original order) on votes, distance, and category.
- Filters: type, status, family. Filters apply to map and list simultaneously.
- Selecting a row highlights and centres the pin; selecting a pin highlights the row.
  Selection is a single shared piece of state.

### S3 — Create a suggestion by searching a place
**As a member, I can search for a place and turn the result into a suggestion.**
- A Places Autocomplete field accepts free text and shows Google's predictions.
- Picking a prediction fetches Place Details in the browser and pre-fills the create form:
  suggested title, address, coordinates.
- On save, the server stores `place_id` plus the fields the user actually kept/typed.
  Google-returned details (photos, ratings, opening hours, editorial summary) are **not**
  stored — see the hard invariant in `design.md`.
- The user can edit any pre-filled field before saving.
- The suggestion's **type is guessed** from the Places `types[]` array and preselected in the
  form's type dropdown; the user can override it (added 2026-08-12, see `design.md` > "Type
  inference from Places").
- The new suggestion appears immediately for every connected member.

### S3b — Create a suggestion from a place already on the map (added 2026-08-12)
**As a member, I can click a place Google already shows on the map and add it as a suggestion.**
- Clicking a base-map POI opens **our** card, not Google's built-in info window (which cannot
  carry our actions), showing name, address and an "Add as suggestion" button.
- "Add as suggestion" opens the create form seeded exactly as S3 seeds it, including the
  guessed type.
- Dismissing the card leaves no suggestion behind; nothing is written until the form is saved.

### S4 — Create a suggestion by dropping a pin
**As a member, I can drop a pin manually anywhere on the map and describe it.**
- Right-clicking the map (long-press on touch) opens a context menu at that point offering
  "Drop a pin here" and "Draw a region here" (revised 2026-08-12); the toolbar entry point
  remains for keyboard and discoverability.
- Entering "drop pin" mode changes the cursor; a single map click places the provisional pin.
- The create form opens with coordinates filled and title/notes empty; `place_id` is null.
- The provisional pin can be dragged before saving; cancelling removes it.

### S5 — Draw a candidate region
**As a member, I can draw a circle or rough polygon to propose an area.**
- Drawing mode offers circle and polygon; the shape can be adjusted before saving.
- Type is forced to `region`; the shape is stored as geometry, and a representative point
  (centroid) is stored in `lat`/`lng` so the region behaves like any other suggestion for
  sorting, distance, and selection.
- Regions render beneath pins and do not participate in pin clustering.

### S6 — Create a suggestion from an external link
**As a member, I can paste an external URL (e.g. an Airbnb listing) and attach it to a suggestion.**
- Pasting a URL into the create form stores it in `external_url`.
- There is no Airbnb API. The user still supplies location by dropping a pin or searching,
  and types the title/notes themselves.
- The server makes a *best-effort* attempt to read the page's link-preview metadata
  (OpenGraph title/description/image) to pre-fill the title field. Failure is normal and
  silent — the user simply types the details.
- The saved suggestion shows the link as a clickable "View listing" affordance.

### S7 — Edit and delete my own suggestion
**As a member, I can edit or delete a suggestion I created.**
- Editable: title, notes, external URL, type, position (drag the pin / redraw the region).
- Moving a pin re-triggers distance recomputation (see `distances`).
- Deleting asks for confirmation only when the suggestion has votes or comments; otherwise
  it deletes with an undo affordance.
- A suggestion already scheduled into the itinerary cannot be deleted — the user is told to
  ask the main admin to unschedule it first.

### S8 — Grouped activities at an accommodation
**As a member, when activities or meals sit at the same place as an accommodation, I see them
grouped inside that accommodation's card rather than as unrelated separate entries.**
- Grouping is by shared `place_id`, or by proximity within a small radius when `place_id` is
  absent on either side.
- The accommodation card shows a count ("3 things here") and expands in place to list them.
- Each grouped child remains individually selectable, votable, and commentable.
- Group members still render their own pins on the map, offset slightly so they are clickable.

### S9 — Move a suggestion through the status flow
**As the main admin, I can shortlist, approve, or reject a suggestion.**
- Allowed transitions: `proposed → shortlisted`, `proposed|shortlisted → approved`,
  any non-terminal → `rejected`, and `rejected → proposed` (undo a rejection).
- `scheduled` is set by the itinerary feature when the suggestion is placed on a day; it is
  not settable directly here.
- Status changes broadcast live; pins and rows restyle without a refresh.
- The confirm/reject controls themselves live in the side panel and are specified in
  `voting-comments`.

### S10 — See details without losing the map
**As a member, I can open a suggestion's full record beside the map.**
- Clicking a pin opens a compact popover card on the map: title, type, vote tally, comment
  count, distance chips.
- "Details" on that card opens the right side panel (desktop) or a bottom sheet (mobile)
  with the full record, a photo strip fetched live from Place Details, notes, external link,
  distances for every family, comments, and admin controls.
- The map stays visible and interactive behind/next to the panel.

## Permissions

| Action | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| View map + suggestion list | Yes | Yes | Yes | No |
| Create suggestion (any type) | Yes | Yes | Yes | No |
| Edit own suggestion | Yes | Yes | Yes | No |
| Edit suggestion by a member of own family | Yes | Yes | No | No |
| Edit any suggestion | Yes | No | No | No |
| Delete own suggestion | Yes | Yes | Yes | No |
| Delete suggestion by own family member | Yes | Yes | No | No |
| Delete any suggestion | Yes | No | No | No |
| Move pin / redraw region (own) | Yes | Yes | Yes | No |
| Change status (shortlist/approve/reject) | Yes | No | No | No |
| Request a link preview | Yes | Yes | Yes | No |

Logged-out users get no access to any trip data; the whole feature is behind session auth.
All permission checks are FastAPI dependencies, never frontend-only.

## Stage availability

| Stage | Behaviour |
|---|---|
| **Planning** | Full behaviour. All create/edit/delete/status actions available per the table above. |
| **Holiday** | Unchanged — suggestions may still be created and still require admin confirmation. The map remains available; on mobile the itinerary takes visual priority (see `holiday-stage`). |
| **End** | Frozen. All reads work; every mutation is rejected by the stage guard. The map becomes a browsable archive. Only the main admin's stage change is permitted. |

## Out of scope (v1)

- Any Airbnb (or other booking site) API integration — none exists publicly.
- A persisted link-preview cache table. Previews are fetched best-effort and held in memory
  only. NOTE: a `link_preview_cache` table is a reasonable later addition if scrape latency
  becomes annoying; deliberately skipped for v1.
- Photo upload onto suggestions. Photos shown come from live Place Details; user-uploaded
  photos use `attachments` and are handled by the archive work in a later milestone.
- Routing or travel time *between* suggestions — that is `route_cache` and belongs to
  `itinerary-timeline`. Home→suggestion distance belongs to `distances`.
- Precise polygon editing (vertex-level tools, holes, multi-polygons). Circle and rough
  polygon only.
- Offline creation or a queued mutation buffer — offline is read-only per `architecture.md`.
- Street View, 3D, or custom map styling beyond the token-driven basemap choice.
- Bulk import of suggestions from a spreadsheet or another trip.
