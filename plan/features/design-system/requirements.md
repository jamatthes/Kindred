# design-system — Requirements

**Read first:** `plan/design-system.md` (the specification this feature implements),
`plan/overview.md`, `plan/architecture.md`, `CLAUDE.md`. Milestone **M0**, with the DesignSync pass
as its gate.

## Summary

`plan/design-system.md` says *what* the design system must be. This feature is the work of *building*
it: the token file, the light and dark theme sets, theme switching with a server-persisted
preference, Tailwind 4 wiring, the base UI primitives, the SVG chart widget library in
`web/src/charts/`, the preference colour ramp, and an internal `/styleguide` gallery.

**Sequencing is the load-bearing requirement.** Token scaffolding lands first with deliberately
provisional values. Then a **DesignSync pass** — a human design decision, not a code task — locks the
final palette and type. Only then are primitives and charts built, and only then does any feature UI
begin. Building feature UI before the token layer exists is how the legacy app ended up with
`#58A6FF` hardcoded in 237 places, and this feature exists specifically to prevent a repeat.

## User stories

### Tokens

**DS-1 — As a developer, I have a three-layer token file I can build every component from.**
- `web/src/design/tokens.css` defines primitives, semantic tokens, and component tokens as CSS custom
  properties, in that order, with the layers visibly separated and commented.
- **Primitives** are raw scales (`--blue-500`, `--gray-100`, `--space-3`, `--text-lg`, `--radius-2`)
  and are never referenced by a component.
- **Semantic** tokens carry meaning (`--color-bg`, `--color-surface`, `--color-surface-raised`,
  `--color-border`, `--color-text`, `--color-text-muted`, `--color-accent`, `--color-success`,
  `--color-warning`, `--color-danger`, `--color-info`, `--family-1`…`--family-8`,
  `--space-inline-sm`, `--radius-card`, `--shadow-card`) and are what components use.
- **Component** tokens exist only where a component needs its own knob (`--button-primary-bg`,
  `--pin-size`, `--timeline-track-h`).
- Spacing primitives are exactly the golden-ratio scale: 5, 8, 13, 21, 34, 55. No in-between values
  exist to be reached for.
- Type primitives are exactly: body 16, large 20, subheading 26, heading 42, display 68.

**DS-2 — As a developer, I am prevented from using raw values.**
- A lint rule fails the build on a hex colour, an `rgb()`/`hsl()` literal, or a raw px value in any
  component file.
- The rule permits raw values only inside `tokens.css` itself and in explicitly annotated generated
  files (e.g. the manifest colour injection described in `plan/features/pwa-push/`).
- The failure message names the token the developer probably wanted.

**DS-3 — As a developer, I never reference a primitive from a component.**
- A lint rule (or a documented review check) flags primitive-layer tokens used outside the semantic
  layer's definitions.

### Themes

**DS-4 — As a user, the app is light by default and legible.**
- Light is the default theme and is the one the DesignSync pass tunes first.
- All semantic tokens have a light value meeting WCAG AA contrast for their intended pairing.

**DS-5 — As a user, I can switch to dark mode and everything still works.**
- A dark set overrides the semantic layer only — no component or primitive changes.
- Dark is independently tuned, not an inversion: surfaces get lighter as they get closer to the user,
  accents are desaturated, and shadows are replaced by surface/border separation.
- Every component, chart, map overlay, and empty state is verified in both themes.

**DS-6 — As a user, my theme choice follows me between devices.**
- I can choose light, dark, or system.
- The choice is persisted to `users.theme_pref` and applies on my next login anywhere.
- "System" tracks `prefers-color-scheme` live, without a reload.
- The theme applies before first paint — there is no flash of the wrong theme on load.
- Logged-out screens respect `prefers-color-scheme`.

**DS-7 — As a developer, theming works through `data-theme` and Tailwind 4.**
- `data-theme="light"` / `"dark"` on `<html>` selects the semantic set.
- Tailwind 4's `@theme` is wired to the same custom properties so utility classes and hand-written CSS
  cannot drift apart.

### Primitives

**DS-8 — As a developer, I have base components covering the product's real needs.**
The initial set, each token-only, keyboard-accessible, and working in both themes:

| Primitive | Requirements |
|---|---|
| `Button` | Primary / secondary / tertiary / danger variants; sizes; loading and disabled states; ≥44px touch target; visible focus ring |
| `Card` | Surface, border, radius, and shadow from tokens; optional header/footer slots; full-card click target variant |
| `Field` | **All six states styled from day one**: default, hover, focus, filled, error, disabled. Label, hint, and error text beneath the field. Error is never colour-only |
| `Sheet` / `SidePanel` | One component, two presentations: right side panel on desktop, bottom sheet on mobile. Focus trap, Escape to close, scroll lock, motion 150–250ms honouring `prefers-reduced-motion` |
| `Table` | Tri-state sort (asc → desc → original), sticky header, sticky first column, tabular figures with right-aligned numerics, full-row click targets, density from spacing tokens, select-all with indeterminate state |
| `Toast` | Transient confirmations of the user's own actions only; supports an undo action; auto-dismiss with a pause on hover/focus; never used for information that must persist |
| `Skeleton` | Structural loading placeholders for lists, cards, and the map panel |
| `EmptyState` | Illustration/icon slot, message, and an inline primary action |

**DS-9 — As a developer, form validation behaves consistently everywhere.**
- Fields validate on blur and re-validate on change once an error has been shown.
- Error text appears beneath the field, paired with an icon — never colour alone.
- Errors are associated with their input for screen readers.

### Preference colour ramp

**DS-10 — As a user, the 0–10 preference scale reads the same everywhere and is colourblind-safe.**
- Tokens `--scale-pref-0` through `--scale-pref-10` define a diverging red → amber → teal-green ramp
  tuned so adjacent steps remain distinguishable under deuteranopia.
- Map region tints, table heat cells, and chart fills all consume the same tokens, so the three views
  are visually identical for the same value.
- **The numeric value always appears as text** alongside the colour. Data never lives in hue alone.
- The ramp has a defined light and dark variant, both meeting contrast requirements against their
  backgrounds and with legible text on top.

### Chart widgets

**DS-11 — As a developer, I have token-aware SVG chart widgets and no chart library.**
The set in `web/src/charts/`:

| Widget | Purpose |
|---|---|
| `HeatMatrix` | Poll score matrix, members × options — the spreadsheet replacement |
| `AvgBar` | Poll option averages and vote tallies |
| `SpreadDots` | Disagreement view: one dot per member on a 0–10 axis, per option |
| `MiniBar` / `Sparkline` | Side-panel stats and summaries |
| `DistributionStrip` | Thumbs voting: up/down/none proportions |

- All colours, spacing, and type come from semantic tokens, so switching theme requires no chart code.
- No charting dependency is added to `package.json`.
- Each widget is responsive and readable at side-panel width (~38% of desktop) and on mobile.
- Each is keyboard-navigable where interactive, and exposes an accessible text summary of its data.

**DS-12 — As a developer, I cannot accidentally draw a dishonest chart.**
The honesty rules from `plan/design-system.md` are enforced by the component APIs, not by convention:
- Bar widgets have **no `baseline` prop**. Bars always start at zero. There is no escape hatch.
- No widget accepts props for gridline decoration, drop shadows, or 3D effects — they do not exist.
- The title prop is named `insight` and its documentation requires a statement of the finding
  ("Cornwall leads, Lake District splits the group"), not a metric name.
- Any widget using the preference ramp requires a text label prop, so colour is never the sole
  carrier of meaning.
- Time-series widgets default to an aspect ratio targeting a ~45° average trend slope.
- Palette choice follows data type: one accent for the key series; categorical, sequential, and
  diverging ramps are separate token sets and are not interchangeable.

### Styleguide

**DS-13 — As a developer or designer, I can see every component in one place.**
- An internal route `/styleguide` renders a gallery: the full token scales, every primitive in every
  state, every chart widget with sample data, the preference ramp, and the empty/loading/error states.
- The page has a theme toggle so both themes can be compared without changing account settings.
- It is authenticated (any logged-in user) but not linked from the main navigation.
- It serves as visual regression by eyeball: reviewing it before and after a change is a required
  step when touching the design system.

### Sequencing

**DS-14 — As the team, we lock the visual direction before building feature UI.**
- Token scaffolding ships first with explicitly provisional values (neutral greys and one placeholder
  accent), clearly labelled as provisional in the file.
- A **DesignSync pass** then locks the real palette, type ramp, radii, and shadows by replacing token
  values only — no component changes should be required.
- Feature UI work does not begin until the DesignSync pass is complete and signed off.
- Because everything references semantic tokens, the pass is a value swap. If it is not, that is a bug
  in the token layer and must be fixed rather than worked around.

## Permissions

| Capability | Main admin | Family admin | Member | Logged-out |
|---|---|---|---|---|
| Use the themed UI | ✅ | ✅ | ✅ | ✅ (login screens are themed) |
| Set own theme preference | ✅ | ✅ | ✅ | ⚠️ local-only, follows `prefers-color-scheme` |
| Set another user's theme | ❌ | ❌ | ❌ | ❌ |
| View `/styleguide` | ✅ | ✅ | ✅ | ❌ |
| Change tokens at runtime | ❌ (build-time only, nobody) | ❌ | ❌ | ❌ |

The styleguide is available to any logged-in user rather than admin-only: it contains no data, and
gating it adds a permission branch to maintain for no benefit. It is simply unlinked.

## Stage availability

The design system is infrastructure and is **stage-independent** — tokens, primitives, charts, theme
switching, and the styleguide behave identically in Planning, Holiday, and End.

Two stage-related obligations fall on this feature:
- Primitives must support an `end`-stage presentation where mutating controls are **absent** rather
  than disabled (see `plan/features/holiday-stage/`), so components must not assume a disabled variant
  is always the right answer.
- The theme preference endpoint is not stage-guarded — a frozen trip must not stop someone switching
  to dark mode.

## Out of scope (v1)

- Choosing the final palette, typefaces, or exact type ramp in this document — that is the DesignSync
  pass's job. This feature builds the machinery that pass operates on.
- Per-user or per-family custom themes and accent colours beyond the eight family slots.
- A high-contrast or forced-colours theme beyond meeting AA in the two shipped themes.
- Design tokens published as an npm package or consumed outside `web/`.
- Storybook or any dedicated component-explorer dependency — `/styleguide` is a plain route.
- Automated visual regression / screenshot diffing (the styleguide is reviewed by eye in v1).
- Animation libraries and scroll-driven animation; motion is CSS transitions within 150–250ms.
- A command palette, drag-and-drop primitives, and other patterns `plan/design-system.md` explicitly
  defers.
- Internationalisation of layout (RTL), though `users.locale` exists in the schema for later.
- Icon library authoring — an existing icon set is used, restyled through tokens.
