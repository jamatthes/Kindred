/**
 * SpreadDots — the disagreement view: one dot per member, per option, on a 0–10 axis.
 *
 * The axis is always the full 0–10 range regardless of how tight the data is — the spread
 * is the message, so there is no `yMin`/zoom prop that could exaggerate or hide it
 * (`plan/features/design-system/design.md`).
 *
 * Layout: a row is a CSS grid — [HTML label] [SVG track] [HTML mean]. No text is drawn
 * inside the SVG. The track SVG has no `viewBox`: dot positions are percentages of the
 * 0–10 axis and radii/heights are real pixels, so the track stretches with the column
 * while the type stays at `--text-sm`. Labels ellipsize (with a `title`) instead of
 * clipping — the old SVG label column silently cut "Cornwall · spread 0.7" to
 * "wall · spread 0.7".
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

/** Percent-of-track positions: the axis is the fixed 0–10 range, never the data's range. */
const axisScale = linearScale([0, 10], [0, 100])

const DOT_R = 5
const DOT_SPACING = 12
/** Minimum track height; a row grows past this only when dots have to fan apart. */
const MIN_TRACK_H = 34

export function SpreadDots({ insight, options, ariaSummary }: SpreadDotsProps) {
  const hasData = options.some((option) => option.scores.length > 0)
  if (!hasData) {
    return <ChartEmptyState insight={insight} message="No votes yet." />
  }

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
      <div className="k-chart__rows" aria-hidden="true">
        {options.map((option) => {
          const positions = layoutDots(option.scores, axisScale, DOT_SPACING)
          const mean = option.scores.length > 0 ? average(option.scores) : null
          // The row grows to fit its own fan, so colliding dots are never pushed into the
          // neighbouring option's track.
          const fan = positions.reduce((max, p) => Math.max(max, Math.abs(p.dy)), 0)
          const trackH = Math.max(MIN_TRACK_H, Math.ceil(fan * 2) + DOT_R * 2 + 4)
          const mid = trackH / 2
          return (
            <div className="k-chart__row" key={option.label}>
              <span className="k-chart__label" title={option.label}>
                {option.label}
              </span>
              <svg className="k-chart__track" width="100%" height={trackH} focusable="false">
                <line className="k-chart__axis" x1={0} y1={mid} x2="100%" y2={mid} />
                {mean !== null ? (
                  <line
                    className="k-chart__mean-tick"
                    x1={`${axisScale(mean)}%`}
                    y1={0}
                    x2={`${axisScale(mean)}%`}
                    y2={trackH}
                  />
                ) : null}
                {positions.map((position, dotIndex) => (
                  <circle
                    key={dotIndex}
                    className="k-chart__dot"
                    cx={`${position.x}%`}
                    cy={mid + position.dy}
                    r={DOT_R}
                  />
                ))}
              </svg>
              <span className="k-chart__value">
                {mean !== null ? mean.toFixed(1) : '—'}
              </span>
            </div>
          )
        })}
        <div className="k-chart__row k-chart__row--ticks">
          <span />
          <span className="k-chart__ticks">
            <span className="k-chart__tick">0</span>
            <span className="k-chart__tick">5</span>
            <span className="k-chart__tick">10</span>
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
