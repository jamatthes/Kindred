# Kindred — Design System

**The rule that governs everything:** components never contain raw values — no hex colors,
no magic px. Only semantic tokens. The legacy app hardcoded `#58A6FF` in 237 places and made
restyling impossible; Kindred must never repeat that.

## Two influences, strictly separated

- **System / information design: Palantir Foundry Map & Maven.** Map center-stage; every
  dataset viewable as table AND map overlay; right side panel for the selected thing's
  details; bottom panel for time (timeline scrubber); overlays/modals only for temporary
  interactions, never for analytical content the user needs to compare side-by-side.
  Data-dense tables are fine — density is a feature.
- **Visual language: friendly consumer product.** Light-first, warm neutrals, soft radii,
  approachable type, roomy touch targets on mobile. Think Airbnb/Linear warmth. Explicitly
  banned: the spy/ops aesthetic (black-on-void, all-caps microtype with extreme tracking,
  "UNCLASSIFIED" cosplay) — and equally, copying designmotionhq's visual styling (its
  *principles* are used below; its look is recognizable AI-generic and off-limits).

Final visual direction (exact palette, type choices) is locked by a **DesignSync pass after
the M0 scaffold**, before any feature UI is built. This document constrains that pass; it
does not pre-pick the palette.

## Brand (added 2026-08-11)

- **Wordmark:** "Kindred" set in **Bricolage Grotesque** (bold, slight negative tracking),
  colored `--color-accent`. Token: `--font-brand` — used for the wordmark only, never body
  copy. The font is self-hosted in production (no runtime Google Fonts dependency).
- **Icon mark:** the compact "K" tile (accent background, `--radius-2`) — used for the PWA
  icon, favicon, and anywhere the full wordmark doesn't fit. Both marks coexist: wordmark
  in the top bar, K tile as the app icon.
- **Trip naming convention:** trips display as **"Destination · Month Year"**
  (e.g. "Cornwall · July 2027"), with the stage chip alongside. While the destination is
  undecided in early Planning, the trip's working name fills the slot until a poll decision
  updates it.

## Token architecture (three layers)

1. **Primitives** — raw scales, never referenced by components:
   `--blue-500`, `--gray-100`, `--space-3`, `--text-lg`, `--radius-2`…
2. **Semantic** — meaning, referenced by components:
   `--color-bg`, `--color-surface`, `--color-surface-raised`, `--color-border`,
   `--color-text`, `--color-text-muted`, `--color-accent`, `--color-success`,
   `--color-warning`, `--color-danger`, `--color-info`, per-family slots
   `--family-1…8`, `--space-inline-sm`, `--radius-card`, `--shadow-card`…
3. **Component** — only where a component needs its own knob:
   `--button-primary-bg`, `--pin-size`, `--timeline-track-h`…

**Theming = swapping the semantic layer.** Light is default. Dark is a separate tuned set
(never a naive inversion — raise surfaces, desaturate accents, reduce shadow reliance).
User preference (`light`/`dark`/`system`) persists server-side on the user record.
Implementation: CSS custom properties + Tailwind 4 `@theme`; `data-theme` on `<html>`.

## Proportional scales (golden-ratio-derived, rounded to practical px)

- **Spacing:** 5 · 8 · 13 · 21 · 34 · 55 (each ≈ previous × 1.6). Every gap uses a step —
  no in-between values.
- **Type:** body 16 → large 20 → subheading 26 → heading 42 (display 68 reserved for
  marketing/empty states). Line-heights and the type ramp finalized in the DesignSync pass.
- **Layout:** primary/secondary splits target ≈ 62/38 (map vs side panel on desktop).
  12-column grid underneath; break it deliberately, not accidentally.
- Ratio is a guide, not a straitjacket — content needs win conflicts.

## Layout system

- **Desktop:** left slim nav rail → map center (~62%) → right side panel (~38%) for the
  selected suggestion/poll/itinerary item; bottom timeline panel collapsible.
- **Top bar (canonical composition, 2026-08-11):** trip name + stage chip (left) ·
  global search "Search places or people" (center) · notification bell with unread badge,
  **family presence stack**, and the primary "Suggest a place" action (right). The primary
  create action lives in the top bar, not floating on the map.
- **Family presence stack:** one avatar per family (family color, initial), overlapping.
  A family's avatar is **full color when at least one member has a live session** and
  greyed/desaturated when nobody is online. Hovering a family opens a tooltip listing its
  members: online members in normal text with a small `--color-success` dot, offline
  members in faint text with a neutral dot; the viewing user is marked "you". Presence is
  ephemeral (derived from live WebSocket sessions — see `architecture.md`), never stored.
  Reference: `design-preview/screen-planning-map.html`.
- **Mobile (holiday-stage priority):** bottom tab nav; map full-bleed; cards appear as
  **bottom sheets** (thumb reach) instead of side panels; "now / next up" is the default
  holiday screen.
- Pin → compact popover card (title, category, votes, comment count, distance chips) →
  "details" opens the side panel / bottom sheet with full record, photo strip, comments,
  admin controls. Cards stay glanceable; the panel does the heavy lifting.

## Map as a data view

- Every dataset renders on the map when it has geometry: poll options tint candidate
  regions by average score; suggestions cluster by type with per-type iconography and
  per-family color accents; live locations/check-ins are family-colored pins.
- **Preference color ramp:** user wants 0=red → 10=green. Implement as a
  **colorblind-safe diverging ramp** (red → amber → teal-green tuned for deuteranopia),
  and the numeric value always appears as text on the label — data never lives in hue
  alone. Ramp defined once as tokens (`--scale-pref-0…10`), reused by map tints, table
  heat cells, and chart fills so all three views read identically.

## Chart widget library (`web/src/charts/`)

Own small SVG components — no heavy chart dependency. All token-aware (colors, spacing,
type from semantic tokens; theme switch is free). Initial set:

| Widget | Used by |
|---|---|
| `HeatMatrix` | Poll score matrix (members × options) — the Excel replacement |
| `AvgBar` | Poll option averages, vote tallies |
| `SpreadDots` | Disagreement view: one dot per member on a 0–10 axis per option |
| `MiniBar` / `Sparkline` | Side-panel stats, expense summaries (post-v1) |
| `DistributionStrip` | Thumbs votes (up/down/none proportions) |

**Honesty rules — enforced by the components, not by convention:**
1. Bars always start at zero (the API has no `baseline` prop).
2. Chart type must match the question: bars compare, lines show change over time,
   parts-of-whole only when slices ≤ 5 (prefer bars regardless).
3. Aspect ratio targets ~45° average trend slope for any time series.
4. Maximize data-ink: no gridline noise, shadows, or 3D — ever.
5. One accent for the key series; categorical/sequential/diverging palettes chosen by
   data type; all ramps colorblind-safe with text fallback.
6. Titles state the insight ("Cornwall leads, Lake District splits the group"), not the
   metric name. Widgets accept `insight` as the title prop to nudge this.

## Pattern decisions (principles adopted; not the source site's styling)

- **Data tables** (poll matrix, suggestion list, families): tri-state sort
  (asc → desc → original), sticky header + sticky first column, tabular figures +
  right-aligned numerics, full-row click targets, density from spacing tokens,
  select-all with indeterminate state where bulk actions exist.
- **Notifications:** bell + unread badge + dropdown list (GitKraken pattern) as the hub;
  toasts only for transient confirmations of *your own* actions, never for information
  that must persist; every notification deep-links.
- **Forms:** all six field states styled from day one (default/hover/focus/filled/error/
  disabled); validate on blur, re-validate on change after first error; error text
  beneath field, never only color. Focus states visible for keyboard nav everywhere.
- **Loading:** skeletons for structural loads (map panel, lists), spinners only for
  sub-second inline waits; optimistic UI for votes/comments with rollback on WS error.
- **Empty states:** every list/map state designed ("No suggestions yet — drop the first
  pin"), with the action inline. First impressions live here.
- **Motion:** 150–250ms, standard easing, motion communicates state change (card in,
  sheet up, pin drop); respect `prefers-reduced-motion`. Nothing decorative.
- **Undo over confirm** for low-stakes destructive actions (delete own comment);
  real confirms reserved for admin-destructive ones (reject suggestion, change stage).
- **Deferred deliberately:** command palette, drag-and-drop *list* reordering (agenda
  lists use explicit controls), scroll-driven animations. Exception (2026-08-11): the
  itinerary **day-timeline mode** is a sanctioned direct-manipulation surface — dragging
  bars to change times is its core interaction, with mandatory keyboard parity (arrows
  nudge, Shift+arrows resize). See `plan/features/itinerary-timeline/design.md`.

## Accessibility baseline

WCAG AA contrast in both themes (checked at token level, once); all interactive elements
keyboard-reachable with visible focus; hit targets ≥ 44px on touch; color never the sole
carrier of meaning (pairs with icon/text everywhere — see preference ramp).
