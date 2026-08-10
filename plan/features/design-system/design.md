# design-system — Design

**Read first:** `plan/design-system.md` (the governing specification), `plan/overview.md`,
`plan/architecture.md`, `CLAUDE.md`, and this feature's `requirements.md`.

This document describes *how* to build what `plan/design-system.md` specifies. Where the two appear
to disagree, `plan/design-system.md` wins.

## Data model

This feature is almost entirely frontend. It touches exactly one persisted field.

### Existing column (from `plan/architecture.md`)

**`users.theme_pref`** — `light` | `dark` | `system`. Already specified. No migration is required by
this feature.

### No proposed additions

- Family colours are **not** stored as hex. `families.color` holds a **token slot** name
  (`family-1`…`family-8`) per `plan/architecture.md`; the actual colour lives in the semantic token
  layer and therefore differs correctly between light and dark themes. Any implementation that writes
  a hex value into `families.color` is a bug.
- The preference ramp is entirely token-side; nothing about it is stored.
- The styleguide has no persistence.

## REST endpoints

This feature **owns no endpoints**. It consumes one that belongs to `foundation`:

| Method | Path | Request | Response | Dependencies |
|---|---|---|---|---|
| `PATCH` | `/api/v1/users/me` | `{ "theme_pref": "dark" }` | updated user | `require_member` — **no stage guard** |

NOTE: `plan/architecture.md` does not enumerate the users router's routes. This feature assumes
`PATCH /api/v1/users/me` exists and accepts `theme_pref`; if `foundation` names it differently, follow
`foundation`'s docs and update this line. The only requirements this feature imposes are that the
field is persisted per user and that the route carries no stage guard.

The current user's `theme_pref` must be included in the app bootstrap payload so the theme can be
applied before first paint (DS-6).

## WebSocket events

None. Theme preference is per-user and per-session; propagating it live between a user's own tabs is
deliberately not done — changing theme on your laptop should not flip your phone mid-use.

## Token architecture

File: `web/src/design/tokens.css`. Three clearly separated, commented sections in this order.

### Layer 1 — Primitives

Raw scales under `:root`. **Never referenced by a component.**

| Group | Tokens |
|---|---|
| Colour ramps | `--gray-0`…`--gray-1000`, `--blue-*`, `--green-*`, `--amber-*`, `--red-*`, `--teal-*` — each an 11-step ramp |
| Spacing | `--space-1: 5px`, `--space-2: 8px`, `--space-3: 13px`, `--space-4: 21px`, `--space-5: 34px`, `--space-6: 55px` |
| Type size | `--text-body: 16px`, `--text-lg: 20px`, `--text-subheading: 26px`, `--text-heading: 42px`, `--text-display: 68px` |
| Type family / weight / line-height | `--font-sans`, `--font-mono`, `--weight-regular/medium/semibold`, `--leading-tight/normal/relaxed` |
| Radius | `--radius-1`…`--radius-4`, `--radius-full` |
| Shadow | `--shadow-1`…`--shadow-3` |
| Duration / easing | `--duration-fast: 150ms`, `--duration-base: 200ms`, `--duration-slow: 250ms`, `--ease-standard` |
| Z-index | `--z-panel`, `--z-sheet`, `--z-popover`, `--z-toast`, `--z-modal` |

The spacing and type values above are fixed by `plan/design-system.md` and are **not** the
DesignSync pass's to change. Colour ramps, font families, radii, and shadows are provisional until
that pass.

### Layer 2 — Semantic

Defined twice: once under `[data-theme="light"]`, once under `[data-theme="dark"]`. Components
reference **only** this layer.

| Group | Tokens |
|---|---|
| Surfaces | `--color-bg`, `--color-surface`, `--color-surface-raised`, `--color-surface-sunken`, `--color-overlay` |
| Lines | `--color-border`, `--color-border-strong`, `--color-focus-ring` |
| Text | `--color-text`, `--color-text-muted`, `--color-text-inverse`, `--color-text-on-accent` |
| Status | `--color-accent`, `--color-success`, `--color-warning`, `--color-danger`, `--color-info`, each with `-bg` and `-border` companions for tinted surfaces |
| Families | `--family-1`…`--family-8`, each with a `-contrast-text` companion |
| Preference ramp | `--scale-pref-0`…`--scale-pref-10`, each with a `-text` companion |
| Spacing aliases | `--space-inline-sm/md/lg`, `--space-stack-sm/md/lg`, `--space-section` |
| Shape | `--radius-card`, `--radius-control`, `--radius-pill` |
| Elevation | `--shadow-card`, `--shadow-panel`, `--shadow-popover` |

### Layer 3 — Component

Only where a component genuinely needs its own knob, defined next to nothing else:
`--button-primary-bg`, `--button-primary-bg-hover`, `--field-border`, `--field-border-error`,
`--pin-size`, `--pin-border-w`, `--timeline-track-h`, `--table-row-h`, `--sheet-width-desktop`,
`--sheet-radius-mobile`. Each resolves to a semantic token, never to a primitive or a literal.

### Dark theme construction rules

Dark is a tuned set, never an inversion (`plan/design-system.md`):

1. **Surfaces get lighter as they get closer to the user.** In light, elevation is expressed by
   shadow; in dark, by surface lightness. `--color-surface-raised` is lighter than `--color-surface`,
   which is lighter than `--color-bg`.
2. **Accents are desaturated and lightened** so they do not vibrate against dark backgrounds.
3. **Shadows are reduced and borders do more work.** `--shadow-card` in dark is subtle; separation
   comes from `--color-border`.
4. **Status colours are re-picked, not reused** — a light-theme red at AA on white is rarely at AA on
   near-black.
5. **The preference ramp is re-tuned**, keeping the same perceptual ordering and the same
   colourblind-safe step separation.

### Preference ramp specification

Eleven steps, 0 → 10, diverging red → amber → teal-green, per `plan/design-system.md`.

- Ordering must be perceptually monotonic in **lightness as well as hue**, so a greyscale or
  deuteranopic viewer still reads the ordering. This is what makes it safe, not the hue choice alone.
- Adjacent steps must be distinguishable under a deuteranopia simulation. If eleven steps cannot be
  made distinct enough, the honest answer is to make the ramp coarser in the middle and lean harder
  on the numeric label — not to add hues that only some people can see.
- Each `--scale-pref-N` has a `--scale-pref-N-text` companion guaranteed to hit AA against it, for the
  numeral drawn on top.
- **Consumers must render the number.** `HeatMatrix` cells, map region tints, and table heat cells all
  draw the value as text. This is a hard rule from the accessibility baseline, not a preference.

The exact colour values are set by the DesignSync pass. This document fixes the structure and the
constraints the pass must satisfy.

## Tailwind 4 wiring

```
@import "tailwindcss";
@import "./tokens.css";

@theme inline {
  --color-bg: var(--color-bg);
  --color-surface: var(--color-surface);
  --spacing-1: var(--space-1);
  --font-size-body: var(--text-body);
  /* …semantic tokens mapped through, primitives deliberately not exposed… */
}
```

- Only the **semantic** layer is exposed to Tailwind. Utility classes must not be able to reach a
  primitive, or the layering rule collapses.
- `@theme inline` (rather than static values) keeps the utilities pointing at live custom properties,
  so `data-theme` switching applies to utility classes and hand-written CSS identically.
- Tailwind's default colour palette, spacing scale, and font sizes are **disabled**. `p-4`, `text-sm`,
  and `bg-blue-500` must not resolve to Tailwind defaults — every utility resolves to a Kindred token
  or does not exist.

## Theme switching

### Applying before first paint (DS-6)

A small blocking inline script in the HTML head, before any stylesheet:

1. Read `theme_pref` from `localStorage` (mirrored from the server on login for exactly this purpose).
2. If it is `system` or absent, evaluate `matchMedia('(prefers-color-scheme: dark)')`.
3. Set `data-theme` on `<html>` immediately.

This script is the one piece of render-blocking JavaScript in the app, and it is worth it — the
alternative is a visible white flash for every dark-mode user on every page load.

### Runtime

- A `ThemeProvider` reads the bootstrap payload's `theme_pref` as the source of truth, reconciles
  `localStorage`, and sets `data-theme`.
- Changing the preference: update `data-theme` and `localStorage` optimistically, then
  `PATCH /api/v1/users/me`. On failure, revert and show an inline error.
- When the preference is `system`, a `matchMedia` change listener updates `data-theme` live with no
  reload.
- Logged-out screens use the same inline script path and follow `prefers-color-scheme` only.
- Add `<meta name="color-scheme" content="light dark">` so browser-rendered UI (scrollbars, form
  controls, the address bar) matches.

## Primitives

All live in `web/src/design/`. Every one: token-only, keyboard-accessible with a visible focus ring,
≥44px touch targets, verified in both themes.

| Component | Key API and behaviour |
|---|---|
| `Button` | `variant: primary \| secondary \| tertiary \| danger`, `size`, `loading`, `disabled`, `iconStart/iconEnd`. Loading keeps the button's width to prevent layout shift. Focus ring uses `--color-focus-ring` and is never removed. |
| `Card` | `as` polymorphic, optional `header`/`footer`, `interactive` for full-card click targets (which renders a real `<button>`/`<a>`, not a div with a handler). |
| `Field` | Wraps input/select/textarea. Props: `label`, `hint`, `error`, `required`, `disabled`. All six states styled. Error renders beneath with an icon, wired via `aria-describedby` and `aria-invalid`. Validates on blur; re-validates on change **after** the first error. |
| `Sheet` / `SidePanel` | One component, two presentations chosen by a media query: right side panel ≥ desktop breakpoint (`--sheet-width-desktop`, ≈38% per the 62/38 split), bottom sheet below it. Focus trap, Escape close, scroll lock, restore focus to the trigger on close. Enter/exit motion within `--duration-base`, reduced to an opacity change under `prefers-reduced-motion`. |
| `Table` | Generic over row type. `columns` declare `align`, `numeric`, `sortable`. Tri-state sort cycles asc → desc → **original order** (the third state is the point — it is not a two-way toggle). Sticky header and sticky first column via CSS `position: sticky`. Numeric columns get `font-variant-numeric: tabular-nums` and right alignment automatically. Optional `selectable` with a header checkbox supporting the indeterminate state. Full-row click via `onRowClick`. Sort state is announced with `aria-sort`. |
| `Toast` | Imperative `toast()` API. `variant`, optional `action` (used for undo), auto-dismiss ~5s, paused on hover/focus, dismissible. Rendered in an `aria-live="polite"` region. **Documented constraint:** never for information that must persist — that is a notification. |
| `Skeleton` | `Skeleton.Text`, `Skeleton.Card`, `Skeleton.Row`, `Skeleton.Map`. Shimmer respects `prefers-reduced-motion` by falling back to a static tint. |
| `EmptyState` | `icon`, `title`, `description`, `action`. Copy guidance in the doc comment: say what is missing and offer the next step ("No suggestions yet — drop the first pin"). |

### Absent vs disabled

Per `plan/features/holiday-stage/`, End-stage controls must be **absent**, not disabled. Primitives
therefore must not couple visibility to the `disabled` prop, and consuming code should conditionally
render rather than disable when an action will never become available again. This is called out in
each primitive's doc comment.

## Chart widgets (`web/src/charts/`)

Hand-written SVG. No chart dependency (`CLAUDE.md`). All colours, spacing, and type from semantic
tokens, so a theme switch requires zero chart code.

### Shared API

Every widget accepts:
- `insight: string` — **the title prop, named to force a finding rather than a metric name.** Doc
  comment gives good and bad examples.
- `data` — a typed, widget-specific shape.
- `height` / responsive width via a container query or ResizeObserver.
- `ariaSummary?: string` — an accessible text equivalent; if omitted, one is generated from the data.
  Every chart is inside a `role="img"` (or a table fallback) so it is never silent to a screen reader.

**Props that deliberately do not exist**, on any widget: `baseline`, `yMin`, `gridlines`,
`shadow`, `depth`/`3d`, `gradientFill`. Their absence is the enforcement mechanism. A comment at the
top of the shared types file states this and points at `plan/design-system.md`.

### Widgets

| Widget | Data | Notes |
|---|---|---|
| `HeatMatrix` | `{ rows: Member[], cols: Option[], values: (0..10 \| null)[][] }` | The poll matrix. Each cell is filled with `--scale-pref-N` **and prints the number** using `--scale-pref-N-text`. Null cells render as an explicit "—" (did not vote), never as a zero. Sticky row and column headers matching the `Table` primitive's behaviour. |
| `AvgBar` | `{ items: { label, value, count }[] }` | Horizontal bars, **always zero-based**. Value printed at the bar end. Single accent for the series; the leading item may be emphasised. No gridlines. |
| `SpreadDots` | `{ options: { label, scores: number[] }[] }` | One row per option, one dot per member on a 0–10 axis, jittered on collision. Mean marked with a distinct tick. This is the disagreement view — the spread is the message, so the axis is always the full 0–10 regardless of data range. |
| `MiniBar` / `Sparkline` | `{ values: number[] }` | Compact side-panel stats. `Sparkline` targets a ~45° average trend slope by choosing its aspect ratio from the data, per the honesty rules. |
| `DistributionStrip` | `{ up: number, down: number, none: number }` | A single stacked strip for thumbs voting. Each segment carries an icon **and** a count label — the three segments are never distinguished by colour alone. |

### Palette rules in code

Three separate token sets, not interchangeable:
- **Categorical** — family slots `--family-1…8`, for "which family/person".
- **Sequential** — a single-hue ramp, for magnitude.
- **Diverging** — `--scale-pref-0…10`, for the preference scale only.

A widget takes its palette from its data type; there is no `colors` prop letting a caller pass
arbitrary values in.

## Styleguide (`/styleguide`)

- A plain authenticated route in `web/src/app/routes`, not linked from navigation. No Storybook
  dependency.
- Sections: token scales (colour swatches with their names and computed values, spacing, type ramp,
  radii, shadows), every primitive in every state, form field states, the preference ramp shown as
  swatches *and* in a `HeatMatrix` *and* as map-style tints so the three can be compared directly,
  every chart widget with realistic sample data, and loading/empty/error states.
- A theme toggle scoped to the page (sets `data-theme` locally) so both themes can be compared without
  changing the account preference.
- A contrast readout beside each colour pairing showing the computed ratio and a pass/fail marker —
  this is what makes "checked at token level, once" (`plan/design-system.md`) actually happen and
  keeps happening.
- Reviewing this page before and after a design-system change is a required step in `tasks.md`.

## The DesignSync pass

A **human design decision point**, not a code task. It sits between token scaffolding and primitive
implementation, and `plan/overview.md` places it immediately after the M0 scaffold, before any
feature UI.

Inputs: the provisional `tokens.css`, the constraints in `plan/design-system.md` (light-first, warm
neutrals, soft radii, approachable type, roomy touch targets; explicitly not the spy/ops aesthetic and
explicitly not designmotionhq's visual styling).

Outputs, all delivered as **token value changes only**:
- Final light and dark colour ramps and every semantic mapping.
- Final font families and the line-height/weight ramp (the five type *sizes* are already fixed).
- Final radii and shadow values.
- Final family slot colours (eight, mutually distinguishable, colourblind-safe as a set).
- Final preference ramp values, validated under a deuteranopia simulation.

**Exit criterion:** the pass is complete when every value in `tokens.css` is intentional and no file
outside `tokens.css` changed. If component code had to change to accommodate the new palette, the
token layer was leaky and that leak must be fixed before proceeding.

## Edge cases and error states

| Case | Behaviour |
|---|---|
| JavaScript disabled or the inline theme script fails | The stylesheet's `@media (prefers-color-scheme: dark)` fallback applies the dark set, so the user gets a sensible theme rather than an unstyled or wrongly-themed page. |
| `theme_pref` PATCH fails | Local theme reverts to the previous value with an inline error. The UI never claims to have saved something it did not. |
| User switches OS theme while set to `system` | `matchMedia` listener updates `data-theme` live; no reload, no flash. |
| Two tabs open, theme changed in one | The other tab picks it up on next load. Live cross-tab sync is deliberately not implemented. |
| Chart with zero data points | Widget renders its own empty state ("No votes yet"), not an empty axis frame. |
| Chart with one data point | Renders honestly as a single bar/dot; `Sparkline` refuses to draw a trend line from one point and shows the value instead. |
| `HeatMatrix` with many members × options | Horizontal scroll inside the container with sticky headers; the page itself never scrolls horizontally. |
| Preference value out of the 0–10 range | Clamped, and a development-mode console error is raised — silent clamping in production, loud failure in development. |
| Null vs zero in chart data | Null renders as an explicit "no data" marker. **Never** as zero. This is called out in the shared types. |
| Family count exceeds eight | Slots cycle with a distinguishing pattern overlay, and a development warning fires. Eight is the designed maximum. |
| `prefers-reduced-motion` enabled | All sheet, toast, skeleton, and pin-drop motion collapses to opacity changes or nothing. No exceptions. |
| Forced-colours / high-contrast OS mode | Components rely on `currentColor` and borders sufficiently to remain usable; verified once on the styleguide page. |
| A token is referenced but undefined | The build lint catches it; at runtime, CSS custom property fallbacks resolve to a visibly wrong magenta so it is caught immediately rather than degrading silently to transparent. |
| Long text in `Button`, `Field` label, or `EmptyState` | Wraps rather than truncating; layout is tested with a doubled-length string on the styleguide. |
