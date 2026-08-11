/**
 * AvgBar — horizontal bars, one per poll option, showing an average score.
 *
 * Honesty rule 1 (`plan/design-system.md`): bars always start at zero. There is no
 * `baseline` prop, no `yMin` prop, and no way to pass one in — the domain is hardcoded to
 * `[0, scaleMax]` below. `AvgBar.test.tsx` asserts this both at the type level and by
 * checking rendered bar geometry for a dataset that never gets near zero.
 */

import type { ChartBaseProps } from './types'
import { ChartEmptyState, VisuallyHidden } from './a11y'
import { clamp, linearScale } from './scales'
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

const CHART_W = 340
const LABEL_W = 104
const ROW_H = 34
const BAR_H = 18
const PAD = 8

export function AvgBar({ insight, items, scaleMax = 10, ariaSummary, emphasize }: AvgBarProps) {
  if (items.length === 0) {
    return <ChartEmptyState insight={insight} message="No votes yet." />
  }

  const leadIndex =
    emphasize ??
    items.reduce((best, item, index, all) => (item.value > all[best].value ? index : best), 0)

  const trackW = CHART_W - LABEL_W - PAD
  const scale = linearScale([0, scaleMax], [0, trackW])
  const height = items.length * ROW_H + 22

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
      <svg className="k-chart__viz" viewBox={`0 0 ${CHART_W} ${height}`} aria-hidden="true">
        <line
          className="k-chart__axis"
          x1={LABEL_W}
          y1={4}
          x2={LABEL_W}
          y2={height - 18}
        />
        {items.map((item, index) => {
          const y = index * ROW_H + 6
          const width = Math.max(0, scale(clamp(item.value, 0, scaleMax)))
          const isLead = index === leadIndex
          return (
            <g key={item.label}>
              <text className="k-chart__label" x={LABEL_W - PAD} y={y + BAR_H - 4} textAnchor="end">
                {item.label}
              </text>
              <rect
                className={isLead ? 'k-chart__bar' : 'k-chart__bar k-chart__bar--dim'}
                x={LABEL_W}
                y={y}
                width={width}
                height={BAR_H}
                rx={3}
              />
              <text className="k-chart__value" x={LABEL_W + width + 6} y={y + BAR_H - 4}>
                {item.value.toFixed(1)}
              </text>
            </g>
          )
        })}
        <text className="k-chart__tick" x={LABEL_W} y={height - 4}>
          0
        </text>
        <text className="k-chart__tick" x={LABEL_W + trackW} y={height - 4} textAnchor="end">
          {scaleMax}
        </text>
      </svg>
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
