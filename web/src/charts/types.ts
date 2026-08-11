/**
 * Shared chart types for `web/src/charts/`.
 *
 * The honesty rules in `plan/design-system.md` ("Chart widget library") are enforced by
 * leaving the following props out of every widget's type entirely — not by convention,
 * not by a lint rule, but by their simply not existing to pass:
 *
 *   - `baseline` — bar widgets are always zero-based. There is no escape hatch.
 *   - `yMin`     — no truncated/zoomed axes.
 *   - `gridlines`— no gridline decoration; data-ink only.
 *   - `shadow` / `depth` / `3d` — no fake depth.
 *   - `gradientFill` — flat fills only.
 *
 * If a future change needs one of these, that is a conversation with
 * `plan/design-system.md` first, not a prop addition. `*.test.tsx` in this directory
 * assert (at the type level, via `expectTypeOf`) that these keys are absent from every
 * bar-family widget's props.
 */

/** Props every chart widget accepts, beyond its own data shape. */
export type ChartBaseProps = {
  /**
   * The title prop — named `insight`, not `title`, to force a finding rather than a
   * metric name.
   *
   * Good: "Cornwall leads Somerset by two full points"
   * Bad:  "Average score by destination"
   */
  insight: string
  /**
   * An accessible text equivalent for the chart's `role="img"` label. When omitted, one
   * is generated from the data so a chart is never silent to a screen reader.
   */
  ariaSummary?: string
}

/** A trip member, as HeatMatrix and SpreadDots key their rows/scores by. */
export type ChartMember = {
  id: string
  label: string
}

/** A poll option / destination, as HeatMatrix and AvgBar key their columns/rows by. */
export type ChartOption = {
  id: string
  label: string
}
