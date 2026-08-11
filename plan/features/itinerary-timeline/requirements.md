# itinerary-timeline — Requirements

Feature 8 in `plan/overview.md`. Milestone M4.

The agreed plan. Everything up to this point is proposal and opinion; this feature is where the
main admin turns approved suggestions into "this is what we are actually doing, and when".
Time lives in a bottom panel, per the Palantir-derived information architecture in
`plan/design-system.md`.

## Concepts

- **Itinerary item** — one thing happening on one day, usually backed by an approved
  suggestion, occasionally added directly by the admin (a ferry crossing, a birthday dinner
  nobody suggested).
- **Day** — a date within the trip's `start_date`…`end_date` range.
- **Timeline scrubber** — the bottom panel spanning the whole trip, used to move between days
  and see the shape of the trip at a glance.
- **Route leg** — the drive between two consecutive items on a day, drawn on the map from a
  cached polyline.
- **Weather strip** — per-day forecast for the day's location, cached with a short TTL.

## User stories

### T1 — Schedule an approved suggestion onto a day
**As the main admin, I can place an approved suggestion onto a specific day.**
- Only suggestions with status `approved` can be scheduled; proposed, shortlisted, and rejected
  ones are not offered.
- I choose a date within the trip range, and optionally a start and end time.
- Scheduling sets the suggestion's status to `scheduled`.
- The item appears immediately for everyone on the day view, the timeline, and the map.

### T2 — Add an item that has no suggestion behind it
**As the main admin, I can add an itinerary item directly.**
- Title and day are required; times, notes, and a location are optional.
- An item with no location does not appear on the map or contribute a route leg, but still
  appears on the day view and the timeline.

### T3 — Edit or remove an item
**As the main admin, I can change an item's day, times, or title, or remove it.**
- Moving an item to another day preserves everything else about it.
- Removing an item returns its suggestion's status from `scheduled` to `approved`, so it goes
  back into the pool rather than vanishing.
- Removal is admin-destructive and uses a confirm dialog.

### T4 — Reorder items within a day
**As the main admin, I can change the order of items within a day using explicit controls.**
- Move up / move down controls on each item, plus a "move to day" action.
- Reordering is immediate and visible to everyone.
- NOTE: *list* drag-and-drop is deliberately deferred per `plan/design-system.md`; the
  agenda list uses explicit controls only. The day-timeline mode (T5b) is the sanctioned
  drag surface — it changes item *times* by direct manipulation, not list order.

### T5b — Edit times on the day timeline (added 2026-08-11)
**As the main admin, I can switch the day view to a horizontal timeline and drag items to
change their times.**
- The day panel offers `Agenda | Timeline` modes; my choice is remembered on this device.
- In Timeline mode, each timed item is a bar on an hour axis; gaps between items are
  visible as empty track, and drive legs draw between located bars — tinted warning when
  the drive is longer than the gap.
- I can drag a bar to move it (15-minute snapping, duration kept) and drag its edges to
  resize; a ghost + time bubble show the change before I drop; everyone else sees the
  update live; a toast lets me Undo.
- Keyboard: arrows nudge, Shift+arrows resize — full parity with dragging.
- Untimed items sit in a shelf below; dragging one onto the track gives it a time.
- Members see the identical timeline read-only. During Holiday, a now-cursor drifts
  across today's track.

### T5 — See a single day in detail
**As a member, I can view one day's plan in order.**
- Items are listed in sequence with times where set, and in `sort` order where not.
- Items with times and items without are visually distinguished — an unscheduled band holds
  the "sometime today" items rather than pretending they have a slot.
- Each item links to its suggestion's full record, including votes and comments.

### T6 — Move through the trip on a timeline
**As a member, I can scrub along a bottom timeline covering the whole trip.**
- The timeline spans `start_date` to `end_date`, whatever the length — a long weekend and a
  three-week trip both render sensibly.
- Day boundaries are marked; hour detail appears when the range is short enough to warrant it
  and thins out as the trip gets longer.
- Clicking or dragging moves the selected day/time; the day view and map follow.
- During the Holiday stage a "now" marker shows the current moment in the trip.
- The panel is collapsible, because the map is the primary surface.

### T7 — See the plan on the map
**As a member, I can see the selected day's items and the drives between them on the map.**
- Items render as numbered pins in sequence.
- Consecutive items with locations are joined by a route line drawn from a cached polyline.
- Selecting an item on the map, the day view, or the timeline selects it in all three.

### T8 — See the weather for each day
**As a member, I can see the forecast for each day of the trip.**
- A weather strip shows a condition and temperature per day, for that day's location.
- Weather is only meaningful within forecast range; days beyond it show no forecast rather
  than a fabricated one.
- The strip appears alongside the timeline and on the day view.

### T9 — Export the confirmed itinerary
**As a member, I can export the itinerary to my own calendar.**
- Download produces a standard `.ics` file covering the confirmed itinerary.
- Timed items become timed events; untimed items become all-day events.
- The export reflects the itinerary at the moment of download; it is not a live subscription.

## Permissions

| Action | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| View day view, timeline, map layer, weather | Yes | Yes | Yes | No |
| Export iCal | Yes | Yes | Yes | No |
| Schedule an approved suggestion onto a day | Yes | No | No | No |
| Add an item with no suggestion | Yes | No | No | No |
| Edit an item (day, times, title) | Yes | No | No | No |
| Reorder items within a day | Yes | No | No | No |
| Remove an item | Yes | No | No | No |
| Set the trip's date range | Yes | No | No | No |

The itinerary is the one place where the main admin's "final say" from `overview.md` is
absolute. Family admins have no elevated rights here at all — their authority covers their own
family, and the itinerary is a whole-trip artefact.

All checks are FastAPI dependencies. Frontend hiding is presentation only.

## Stage availability

| Stage | Behaviour |
|---|---|
| **Planning** | The admin builds the itinerary ahead of time. Full editing. The timeline shows the planned trip; there is no "now" marker because the trip has not started. |
| **Holiday** | The itinerary is the primary surface. Full editing continues — plans change on the road. The "now" marker is live, and the timeline defaults to today. |
| **End** | Frozen read-only. The itinerary becomes the spine of the archive. Viewing, scrubbing, and iCal export all still work; every mutation is rejected. No Directions or weather call is made in End — cached values only. |

## Out of scope (v1)

- **List drag-and-drop reordering.** Deferred in `design-system.md`; the agenda list uses
  explicit move controls. (Time-editing by drag lives in the day-timeline mode, T5b —
  in scope.)
- Per-family divergent itineraries (one family going to the beach while another goes hiking).
  v1 has one itinerary for the trip.
- The "now / next up" mobile view — that belongs to `holiday-stage`.
- Two-way calendar sync, live iCal subscription feeds, or Google Calendar integration. Export
  is a one-time download.
- Conflict detection or automatic scheduling suggestions ("these two overlap", "you can't get
  there in time"). The admin is trusted.
- Booking, reservation, or confirmation-number tracking.
- Cost or expense tracking against itinerary items (post-v1 per the chart widget table).
- Travel legs as first-class editable records. Routes are derived from consecutive items.
  NOTE: `itinerary_items.kind` was considered for this and deliberately skipped for v1; it
  remains a reasonable future addition if travel needs its own row.
- Multi-day items spanning a date range as a single record (a three-day festival is entered as
  three items).
- Packing lists, checklists, or documents attached to days.
