/**
 * Accessibility helpers shared by the chart widgets.
 *
 * Every widget wraps its SVG in a `role="img"` element carrying an `aria-label`, and
 * additionally renders a visually-hidden `<table>` fallback with the same data, so a
 * screen reader user gets the real numbers rather than a generated one-line summary.
 * Charts must never be aria-black-holes (`plan/features/design-system/requirements.md`
 * DS-11).
 */

import type { ReactNode } from 'react'
import './charts.css'

/**
 * Standard "sr-only" clip technique: present in the accessibility tree, invisible and
 * out of layout flow for sighted users. Used to wrap the table fallback next to each
 * chart's SVG.
 */
export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="k-chart-visually-hidden">{children}</span>
}

/** Shared "no data yet" body for any widget with zero data points (design.md edge case:
 *  an honest empty state, never an empty axis frame). */
export function ChartEmptyState({
  insight,
  message,
}: {
  insight: string
  message: string
}) {
  return (
    <figure className="k-chart" role="img" aria-label={`${insight} — ${message}`}>
      <figcaption className="k-chart__insight">{insight}</figcaption>
      <p className="k-chart__empty">{message}</p>
    </figure>
  )
}
