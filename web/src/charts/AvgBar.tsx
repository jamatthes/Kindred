/**
 * AvgBar — horizontal bars, one per poll option, showing an average score.
 *
 * Honesty rule 1 (`plan/design-system.md`): bars always start at zero. There is no
 * `baseline` prop, no `yMin` prop, and no way to pass one in — the domain is hardcoded to
 * `[0, scaleMax]` below. `AvgBar.test.tsx` asserts this both at the type level and by
 * checking rendered bar geometry for a dataset that never gets near zero.
 *
 * Layout: a row is a CSS grid — [HTML label] [SVG track] [HTML value]. No text is drawn
 * inside the SVG. The track SVG has no `viewBox`: bar widths are percentages of the track
 * and heights are real pixels, so the geometry stretches with the column while nothing
 * about it scales the page's type. Labels ellipsize (with a `title`) rather than clip.
 */

import type { ChartBaseProps } from './types'
import { ChartEmptyState, VisuallyHidden } from './a11y'
import { clamp } from './scales'
import './charts.css'

export type AvgBarItem = {
  label: string
  /** Average score, 0–10. */
  value: number
  /** Respondent count behind the average — shown in the accessible summary and table. */
  count?: number
}

export type AvgBarProps = ChartBaseProps & {
  items: AvgBarItem[]
  /**
   * The top of the axis. Defaults to 10, the preference scale's natural ceiling. This is
   * the axis *extent*, not a baseline — bars still always start at zero regardless of
   * this value.
   */
  scaleMax?: number
  /** Index into `items` to draw with the accent colour; the rest render dimmed — "one
   *  accent for the key series" (honesty rule 5). Defaults to the highest-value row. */
  emphasize?: number
}

/** Bar height in CSS pixels. Fixed, because the track no longer scales with the column. */
const BAR_H = 18

export function AvgBar({ insight, items, scaleMax = 10, ariaSummary, emphasize }: AvgBarProps) {
  if (items.length === 0) {
    return <ChartEmptyState insight={insight} message="No votes yet." />
  }

  const leadIndex =
    emphasize ??
    items.reduce((best, item, index, all) => (item.value > all[best].value ? index : best), 0)

  const summary =
    ariaSummary ??
    `${insight}. ` +
      items
        .map(
          (item) =>
            `${item.label} ${item.value.toFixed(1)}${item.count != null ? ` (${item.count} votes)` : ''}`,
        )
        .join('; ') +
      `, out of ${scaleMax}.`

  const hasCounts = items.some((item) => item.count != null)

  return (
    <figure className="k-chart" role="img" aria-label={summary}>
      <figcaption className="k-chart__insight">{insight}</figcaption>
      <div className="k-chart__rows" aria-hidden="true">
        {items.map((item, index) => {
          // Zero-based by construction: the rect's x is 0 and its width is the value's
          // share of the axis. There is no other number that could be put here.
          const percent = (clamp(item.value, 0, scaleMax) / scaleMax) * 100
          const isLead = index === leadIndex
          return (
            <div className="k-chart__row" key={item.label}>
              <span className="k-chart__label" title={item.label}>
                {item.label}
              </span>
              <svg className="k-chart__track" width="100%" height={BAR_H} focusable="false">
                <line className="k-chart__axis" x1={0} y1={0} x2={0} y2={BAR_H} />
                <rect
                  className={isLead ? 'k-chart__bar' : 'k-chart__bar k-chart__bar--dim'}
                  x={0}
                  y={0}
                  width={`${percent}%`}
                  height={BAR_H}
                  rx={3}
                />
              </svg>
              <span className="k-chart__value">{item.value.toFixed(1)}</span>
            </div>
          )
        })}
        <div className="k-chart__row k-chart__row--ticks">
          <span />
          <span className="k-chart__ticks">
            <span className="k-chart__tick">0</span>
            <span className="k-chart__tick">{scaleMax}</span>
          </span>
          <span />
        </div>
      </div>
      <VisuallyHidden>
        <table>
          <caption>{insight}</caption>
          <thead>
            <tr>
              <th scope="col">Option</th>
              <th scope="col">Average</th>
              {hasCounts ? <th scope="col">Votes</th> : null}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.label}>
                <th scope="row">{item.label}</th>
                <td>{item.value.toFixed(1)}</td>
                {hasCounts ? <td>{item.count ?? '—'}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </VisuallyHidden>
    </figure>
  )
}
