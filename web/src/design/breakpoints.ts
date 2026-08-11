/**
 * Breakpoints that a component has to ask about in JavaScript rather than in CSS.
 *
 * A media query cannot read a custom property, so a layout decision made in both places has
 * to be written in both places. Writing it *here*, in the design layer, at least keeps the
 * two copies next to their token and makes the duplication a known one rather than a number
 * somebody typed into a component.
 *
 * Mirrors `--breakpoint-panel` in `tokens.components.css`. Change both together.
 */

/** Below this the side panel becomes a bottom sheet (`plan/design-system.md` > Mobile). */
export const PANEL_SHEET_QUERY = '(max-width: 900px)'

/**
 * Below this a date/time picker opens in the `BottomSheet` rather than a popover
 * (design-system Phase 11 — "mobile is not a shrunken popover").
 *
 * The same width as the panel's, and deliberately not an alias of it: they agree today
 * because a two-month calendar and a 38% panel stop fitting at about the same place, but
 * they are two decisions, and aliasing would mean a future change to the panel silently
 * moved every picker. Mirrors `--breakpoint-picker-sheet`.
 */
export const PICKER_SHEET_QUERY = '(max-width: 900px)'
