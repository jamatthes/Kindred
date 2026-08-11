/**
 * SpreadDots — the disagreement view: one dot per member, per option, on a 0–10 axis.
 *
 * The axis is always the full 0–10 range regardless of how tight the data is — the spread
 * is the message, so there is no `yMin`/zoom prop that could exaggerate or hide it
 * (`plan/features/design-system/design.md`).
 */

import type { ChartBaseProps } from './types'
import { ChartEmptyState, VisuallyHidden } from './a11y'
import { average, layoutDots, linearScale } from './scales'
import './charts.css'

export type SpreadDotsOption = {
  label: string
  /** One score per member who voted, 0–10. */
  scores: number[]
}

export type SpreadDotsProps = ChartBaseProps & {
  options: SpreadDotsOption[]
}

const CHART_W = 340
const LABEL_W = 104
const ROW_H = 52
const PAD = 8
const DOT_SPACING = 12

export function SpreadDots({ insight, options, ariaSummary }: SpreadDotsProps) {
  const hasData = options.some((option) => option.scores.length > 0)
  if (!hasData) {
    return <ChartEmptyState insight={insight} message="No votes yet." />
  }

  const trackW = CHART_W - LABEL_W - PAD
  const scale = linearScale([0, 10], [0, trackW])
  const height = options.length * ROW_H + 22

  const summary =
    ariaSummary ??
    `${insight}. ` +
      options
        .map((option) => {
          if (option.scores.length === 0) return `${option.label}: no votes yet`
          const mean = average(option.scores)
          const min = Math.min(...option.scores)
          const max = Math.max(...option.scores)
          return `${option.label}: mean ${mean.toFixed(1)}, ${option.scores.length} scores ranging ${min}–${max}`
        })
        .join('; ')

  return (
    <figure className="k-chart" role="img" aria-label={summary}>
      <figcaption className="k-chart__insight">{insight}</figcaption>
      <svg className="k-chart__viz" viewBox={`0 0 ${CHART_W} ${height}`} aria-hidden="true">
        {options.map((option, index) => {
          const y = index * ROW_H + 22
          const positions = layoutDots(option.scores, scale, DOT_SPACING)
          const mean = option.scores.length > 0 ? average(option.scores) : null
          return (
            <g key={option.label}>
              <text className="k-chart__label" x={LABEL_W - PAD} y={y + 4} textAnchor="end">
                {option.label}
              </text>
              <line
                className="k-chart__axis"
                x1={LABEL_W}
                y1={y}
                x2={LABEL_W + trackW}
                y2={y}
              />
              {mean !== null ? (
                <line
                  className="k-chart__mean-tick"
                  x1={LABEL_W + scale(mean)}
                  y1={y - 12}
                  x2={LABEL_W + scale(mean)}
                  y2={y + 12}
                />
              ) : null}
              {positions.map((position, dotIndex) => (
                <circle
                  key={dotIndex}
                  className="k-chart__dot"
                  cx={LABEL_W + position.x}
                  cy={y + position.dy}
                  r={5}
                />
              ))}
            </g>
          )
        })}
        <text className="k-chart__tick" x={LABEL_W} y={height - 4}>
          0
        </text>
        <text className="k-chart__tick" x={LABEL_W + trackW / 2} y={height - 4} textAnchor="middle">
          5
        </text>
        <text className="k-chart__tick" x={LABEL_W + trackW} y={height - 4} textAnchor="end">
          10
        </text>
      </svg>
      <VisuallyHidden>
        <table>
          <caption>{insight}</caption>
          <thead>
            <tr>
              <th scope="col">Option</th>
              <th scope="col">Mean</th>
              <th scope="col">Scores</th>
            </tr>
          </thead>
          <tbody>
            {options.map((option) => (
              <tr key={option.label}>
                <th scope="row">{option.label}</th>
                <td>{option.scores.length > 0 ? average(option.scores).toFixed(1) : '—'}</td>
                <td>{option.scores.length > 0 ? option.scores.join(', ') : 'no votes yet'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </VisuallyHidden>
    </figure>
  )
}
