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
