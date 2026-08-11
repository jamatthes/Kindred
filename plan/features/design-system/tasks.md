# design-system — Tasks

**Read first:** `plan/design-system.md`, this feature's `requirements.md` and `design.md`, plus
`plan/overview.md` and `CLAUDE.md`. Milestone **M0**.

**Sequencing is mandatory.** Phases 1–3 (token scaffolding) come first. Phase 4 is the **DesignSync
pass**, a blocking human checkpoint. Phases 5+ (primitives, charts) come after it. **No feature UI
work in any other feature may begin until Phase 4 is checked.** Building components against
provisional tokens is fine and expected; building *feature screens* against them is not.

---

## Phase 1 — Token scaffolding (provisional values)

- [ ] Create `web/src/design/tokens.css` with the three commented layers in order: primitives,
      semantic, component.
- [ ] Add a header comment stating that colour, font, radius, and shadow values are **PROVISIONAL
      until the DesignSync pass** and that spacing/type sizes are fixed by `plan/design-system.md`.
- [ ] Primitives: colour ramps (provisional neutral greys plus one placeholder accent), spacing
      `5/8/13/21/34/55`, type sizes `16/20/26/42/68`, weights, line-heights, radii, shadows,
      durations `150/200/250`, easing, z-index scale.
- [ ] Semantic layer under `[data-theme="light"]`: surfaces, borders, text, status colours with
      `-bg`/`-border` companions, `--family-1…8` with contrast companions, spacing aliases, shape,
      elevation.
- [ ] Semantic layer under `[data-theme="dark"]` following the five dark-construction rules in
      `design.md` — raised surfaces lighter, accents desaturated, shadows reduced, status colours
      re-picked, ramp re-tuned.
- [ ] Preference ramp `--scale-pref-0…10` plus `-text` companions, provisional values, in both themes.
- [ ] Component layer with the initial knobs, each resolving to a semantic token.

**Verify:** Load a scratch page that renders every token as a labelled swatch/box in both themes by
flipping `data-theme` in devtools. Every token resolves — nothing renders as the fallback magenta.

---

## Phase 2 — Tailwind wiring and lint guards

- [ ] Wire Tailwind 4 `@theme inline` to the **semantic** tokens only; do not expose primitives.
- [ ] Disable Tailwind's default colour palette, spacing scale, and font sizes so no default utility
      resolves.
- [ ] Add a stylelint/ESLint rule failing the build on hex colours, `rgb()`/`hsl()` literals, and raw
      px values outside `tokens.css`.
- [ ] Allow-list the generated manifest colour injection described in `plan/features/pwa-push/`.
- [ ] Make the lint error message name the likely intended token.
- [ ] Add a rule (or a documented review checklist item) flagging primitive-layer tokens referenced
      outside the semantic layer.
- [ ] Add a CSS custom property fallback chain that resolves to a loud magenta for undefined tokens.

**Verify:** Add a temporary component containing `color: #ff0000` and `padding: 7px`, confirm both
fail lint with helpful messages, then remove it. Confirm `bg-blue-500` and `p-4` do not resolve to
Tailwind defaults.

---

## Phase 3 — Theme switching

- [ ] Add the blocking inline head script: read `localStorage` theme, fall back to `matchMedia`, set
      `data-theme` before any stylesheet loads.
- [ ] Add `<meta name="color-scheme" content="light dark">`.
- [ ] Add `@media (prefers-color-scheme: dark)` fallback rules so a failed script still themes
      correctly.
- [ ] `ThemeProvider` reading `theme_pref` from the bootstrap payload, reconciling `localStorage`,
      and setting `data-theme`.
- [ ] `matchMedia` listener applying live changes when the preference is `system`.
- [ ] Theme control (light / dark / system) in settings, saving optimistically via
      `PATCH /api/v1/users/me` with revert-and-inline-error on failure.
- [ ] Confirm with `foundation` that `theme_pref` is in the bootstrap payload and the route is not
      stage-guarded; update `design.md`'s endpoint note if the route differs.

**Verify:** Set dark and hard-reload — **no flash of light theme**. Set `system`, change the OS
theme, and watch it switch live without a reload. Log in on a second browser and confirm the
preference followed. Disable JavaScript and confirm the media-query fallback still themes the page.

---

## Phase 4 — 🔒 DesignSync pass (BLOCKING — human checkpoint)

> **Do not start Phase 5 or any feature UI in any other feature until this box is checked.**
> This is a design decision made by a human, not a task an agent completes autonomously.

- [ ] Run the DesignSync pass against the constraints in `plan/design-system.md`: light-first, warm
      neutrals, soft radii, approachable type, roomy touch targets; **not** the spy/ops aesthetic and
      **not** designmotionhq's visual styling.
- [ ] Lock final light and dark colour ramps and every semantic mapping.
- [ ] Lock font families and the line-height/weight ramp (the five type sizes are already fixed).
- [ ] Lock radii and shadow values.
- [ ] Lock the eight family slot colours — mutually distinguishable and colourblind-safe as a set.
- [ ] Lock the preference ramp, validated under a deuteranopia simulation, monotonic in lightness as
      well as hue.
- [ ] Remove the "PROVISIONAL" header comment from `tokens.css`.
- [ ] **Exit criterion:** confirm the diff for this pass touches `tokens.css` and nothing else. If any
      component file had to change, the token layer leaked — fix the leak, then re-run this check.

**Verify:** `git diff --stat` for the pass shows only `tokens.css`. Every colour pairing on the
styleguide (built in Phase 8, or a temporary swatch page if running before it) passes WCAG AA.
Sign-off recorded before Phase 5 begins.

---

## Phase 5 — Base primitives, part one

- [ ] `Button` — four variants, sizes, loading (width preserved), disabled, icon slots, visible focus
      ring, ≥44px touch target.
- [ ] `Card` — polymorphic `as`, header/footer slots, `interactive` variant rendering a real
      button/anchor rather than a div with a click handler.
- [ ] `Field` — all six states, label/hint/error, `aria-describedby` + `aria-invalid`, error icon plus
      text, validate on blur and re-validate on change after first error.
- [ ] `Skeleton` — Text/Card/Row/Map variants, shimmer collapsing to a static tint under
      `prefers-reduced-motion`.
- [ ] `EmptyState` — icon, title, description, inline action, with copy guidance in the doc comment.
- [ ] Add the "absent vs disabled" note to each primitive's doc comment.

**Verify:** `npm test` — Vitest covering each Field state, Button loading/disabled semantics, and
`interactive` Card rendering a focusable element. Keyboard-tab through a scratch page containing all
five and confirm every focus ring is visible in both themes.

---

## Phase 6 — Base primitives, part two

- [ ] `Sheet` / `SidePanel` — one component, side panel on desktop (`--sheet-width-desktop` ≈38%),
      bottom sheet on mobile; focus trap, Escape close, scroll lock, focus restored to trigger;
      motion within `--duration-base` and reduced-motion fallback.
- [ ] `Table` — tri-state sort cycling asc → desc → **original order**, sticky header, sticky first
      column, tabular figures with auto right-alignment for numeric columns, full-row click,
      optional selection with an indeterminate header checkbox, `aria-sort` announcements.
- [ ] `Toast` — imperative API, variants, `action` slot for undo, auto-dismiss with pause on
      hover/focus, `aria-live="polite"`, plus the documented "never for persistent information"
      constraint.

**Verify:** `npm test` — tri-state sort returns to original order on the third click; indeterminate
state renders correctly; Sheet traps focus and restores it on close. Manually confirm the Sheet
becomes a bottom sheet at a mobile viewport and that a wide Table scrolls inside its container
without the page scrolling horizontally.

---

## Phase 7 — Chart widget library

- [x] Create `web/src/charts/` with shared types and a header comment listing the props that
      deliberately do not exist (`baseline`, `yMin`, `gridlines`, `shadow`, `depth`, `gradientFill`)
      and citing `plan/design-system.md`.
- [x] Shared API: `insight` title prop with good/bad examples in its doc comment, `ariaSummary` with
      auto-generation, responsive sizing, `role="img"` wrapper. (`HeatMatrix` is the documented
      exception: it's a real `<table>`, not SVG, so it carries its accessible structure natively
      instead of a `role="img"` wrapper — see `HeatMatrix.tsx`'s header comment.)
- [ ] Three separate palette token sets (categorical / sequential / diverging) with no caller-supplied
      `colors` prop. (Categorical `--family-N` and diverging `--scale-pref-N` exist and are usable;
      no widget consumes a distinct sequential single-hue ramp yet, and no such token set is defined
      separately from the status colours.)
- [x] `HeatMatrix` — cells filled from `--scale-pref-N`, **number printed in every cell**, null
      rendered as "—" not zero, sticky row/column headers.
- [x] `AvgBar` — horizontal, always zero-based, value printed at bar end, no gridlines.
- [x] `SpreadDots` — full 0–10 axis always, one dot per member, collision jitter, mean tick.
- [x] `MiniBar` / `Sparkline` — compact; `Sparkline` picks aspect ratio targeting a ~45° trend slope
      and refuses to draw a trend from a single point.
- [x] `DistributionStrip` — stacked segments each carrying an icon and a count label.
- [x] Per-widget empty states ("No votes yet"), not empty axis frames.
- [x] Confirm `package.json` gained **no** charting dependency.

**Verify:** `npm test` — assert `baseline` is not in any bar widget's prop types; assert null data
renders "—" and not a zero bar; assert `AvgBar` axis starts at zero for a dataset ranging 7–9; snapshot
each widget in both themes. Confirm `npm ls` shows no chart library.

---

## Phase 8 — Styleguide route

- [x] Authenticated `/styleguide` route, not linked from navigation, no Storybook dependency.
- [x] Token sections: colour swatches with names and computed values, spacing scale, type ramp, radii,
      shadows.
- [ ] Every primitive in every state, including all six Field states. (Only what exists in
      `web/src/app/ui/` and `web/src/design/` today is shown — `Button`, `Field`, `Banner`, `Spinner`,
      `Toast`, `Skeleton`, `BottomSheet`, `IdentityBadge`. `Card`, `Table`, a general-purpose
      `EmptyState`, and a dedicated `Chip` are not implemented yet, so they aren't in the gallery.
      Field's hover state has no static representation — the gallery notes that it must be checked by
      tabbing/pointing manually. Real focus is demonstrated with an actually-focused field.)
- [x] Preference ramp shown three ways side by side — swatches, a `HeatMatrix`, and map-style tints —
      so the three views can be confirmed identical.
- [x] Every chart widget with realistic sample data, plus each one's empty and single-point states.
- [ ] Loading, empty, and error states for lists and panels.
- [x] Page-scoped theme toggle setting `data-theme` locally.
- [x] Contrast readout beside each colour pairing showing the computed ratio and pass/fail.
- [ ] Doubled-length-string test rendering for Button, Field label, and EmptyState.

**Verify:** Open `/styleguide` in both themes and confirm every contrast readout passes AA. Confirm
the preference ramp reads identically across the three presentations. Screenshot both themes and
attach to the DesignSync sign-off record.

---

## Phase 9 — Accessibility and cross-cutting verification

- [ ] Deuteranopia simulation pass over the preference ramp and the eight family slots, in both
      themes.
- [ ] Keyboard-only traversal of the entire styleguide — every interactive element reachable with a
      visible focus ring.
- [ ] Screen-reader pass: charts announce their `ariaSummary`; Table announces `aria-sort`; Toast
      announces politely without stealing focus.
- [ ] `prefers-reduced-motion` pass with the OS setting enabled — no sheet slide, no shimmer, no pin
      drop.
- [ ] Forced-colours / high-contrast OS mode check on the styleguide.
- [ ] Touch-target audit at a mobile viewport — everything interactive ≥44px.
- [ ] Confirm no raw hex or magic px exists anywhere outside `tokens.css`.

**Verify:** Lighthouse accessibility audit on `/styleguide` with no contrast or ARIA failures; manual
reduced-motion and forced-colours passes recorded; a repository-wide grep for `#[0-9a-fA-F]{3,6}`
outside `tokens.css` and the allow-listed generated files returns nothing.

---

## Phase 10 — Documentation and handoff

- [ ] Add a short `web/src/design/README.md` pointing at `plan/design-system.md` and this feature's
      docs, stating the token-only rule and the primitive-vs-semantic layering rule.
- [ ] Document the "review `/styleguide` before and after any design-system change" requirement.
- [ ] Update these docs if anything changed during implementation (docs-first rule in `CLAUDE.md`).
- [ ] Announce to the other feature tracks that Phase 4 is complete and feature UI may begin.

**Verify:** A developer unfamiliar with the project can read `web/src/design/README.md`, open
`/styleguide`, and build a correctly-tokenised component without asking which colour to use.

---

## Phase 11 — Date and time picker components (added 2026-08-11)

No date/time picker was ever specced; native `<input type="date">` is what the admin console
ships. Consumers queued behind this: trip dates (admin-console Section 1 + AC-0), itinerary
day/time editing and "give it a time" (M4), suggestion date windows (M3+). Build once, here.

- [ ] `DateRangePicker` — the trip-dates case: one calendar surface, click start then end,
      range highlighted; typing remains possible (the input is the accessible base, the
      calendar is progressive enhancement); no six-click month spelunking — year/month jump
      controls and "next weekend / next week" quick-picks where the caller opts in.
- [ ] `DatePicker` — single date; same base; trip-aware variant that, given the trip's date
      span, renders those days as the primary strip (an itinerary item is almost always
      scheduled inside the trip) with the full calendar one gesture away.
- [ ] `TimeField` — time-of-day entry snapping to the itinerary's 15-minute grid
      (`--daytrack-snap`), typeable ("14:30"), with a wheel/list on touch; pairs with
      `DatePicker` for the "give it a time" flow.
- [ ] **Range coupling (user ruling 2026-08-11):** when start and end are separate fields,
      the end field's minimum is the chosen start date — earlier days render disabled and
      unclickable — and opening the end picker **starts its calendar at the start date's
      month**, never at today (observed bug: start=December, end picker opened at August).
      Symmetrically, picking an end before re-opening start caps start's maximum. If a new
      start lands after the current end, the end clears with an inline explanation rather
      than silently holding an invalid range.
- [ ] **Range interaction:** hover paints a live preview of the span; first click locks
      start, second locks end; the edges stay adjustable without starting over. Two months
      render side by side on desktop so a range crosses the boundary without paging.
- [ ] **Presets, caller-supplied:** the component accepts quick-pick chips; trip creation
      passes trip-shaped ones ("This weekend", "A week", "A fortnight" anchored on the
      chosen start) — not analytics presets. Presets are one click, never mandatory.
- [ ] **Mobile is not a shrunken popover:** below the tablet breakpoint the picker opens in
      the existing `BottomSheet` as a full-height vertically scrolling calendar, today
      anchored at the top.
- [ ] Both themes, token-only, keyboard complete (arrows move days, PgUp/Dn months,
      Shift+PgUp/Dn years, Enter confirms, Escape closes, typed entry always works),
      `--hit-target` on touch, and honest fallback: if JS fails, the native input still
      submits.
- [ ] Styleguide section with all three, both themes, disabled/error states.
- [ ] Swap into the admin console's trip dates (the only shipped consumer) without API change.

**Verify:** in the styleguide, pick a trip range with two clicks and no month navigation for
adjacent months; set an itinerary-style time by typing and by wheel; tab through the whole
range picker without a mouse; `npm run verify` green.