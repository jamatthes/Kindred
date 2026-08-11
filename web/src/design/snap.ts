/**
 * The itinerary's time grid, in a form JavaScript can do arithmetic with.
 *
 * `--daytrack-snap` (tokens.components.css) is the CSS half of this decision: it sizes the
 * day-track's grid lines. `TimeField` has to *round to* the same interval, and a custom
 * property is a string a component cannot divide by, so the number is written here as well —
 * the same known, commented duplication `breakpoints.ts` carries for `--breakpoint-panel`.
 *
 * Change both together.
 */

/** Minutes per grid step on the itinerary day track (`plan/features/itinerary-timeline`). */
export const DAYTRACK_SNAP_MINUTES = 15
