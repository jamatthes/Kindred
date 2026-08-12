/**
 * MiniBar / Sparkline — compact side-panel stats (side-panel width, expense summaries).
 *
 * `MiniBar` is a small zero-based bar-per-value strip; it has no `baseline` prop for the
 * same reason `AvgBar` doesn't. `Sparkline` is for genuine time series: it picks its
 * aspect ratio to target a ~45° average trend slope (honesty rule 3), and — per the
 * edge-case table in `plan/features/design-system/design.md` — refuses to draw a trend
 * line from a single point, rendering the value with `MiniBar` instead.
 *
 * Neither draws any text. Both render at their intrinsic pixel size (`k-chart__viz--fixed`)
 * rather than stretching to the container: a sparkline whose aspect ratio was computed to
 * target a ~45° slope stops telling the truth the moment a container rescales it.
 */

import type { ChartBaseProps } from './types'
import { ChartEmptyState, VisuallyHidden } from './a11y'
import { linearScale, slopeTargetWidth } from './scales'
import './charts.css'

export type MiniBarProps = ChartBaseProps & {
  values: number[]
}

const BAR_H = 32
const BAR_W = 10
const BAR_GAP = 4

export function MiniBar({ insight, values, ariaSummary }: MiniBarProps) {
  if (values.length === 0) {
    return <ChartEmptyState insight={insight} message="No data yet." />
  }

  const max = Math.max(...values, 0)
  const scale = linearScale([0, max || 1], [0, BAR_H])
  const width = values.length * (BAR_W + BAR_GAP) - BAR_GAP

  const summary = ariaSummary ?? `${insight}. Values: ${values.join(', ')}.`

  return (
    <figure className="k-chart" role="img" aria-label={summary}>
      <figcaption className="k-chart__insight">{insight}</figcaption>
      <svg
        className="k-chart__viz k-chart__viz--fixed"
        viewBox={`0 0 ${width} ${BAR_H}`}
        width={width}
        height={BAR_H}
        aria-hidden="true"
      >
        {values.map((value, index) => {
          const h = Math.max(0, scale(Math.max(0, value)))
          const x = index * (BAR_W + BAR_GAP)
          return (
            <rect
              key={index}
              className="k-chart__bar"
              x={x}
              y={BAR_H - h}
              width={BAR_W}
              height={h}
              rx={2}
            />
          )
        })}
      </svg>
      <VisuallyHidden>
        <table>
          <caption>{insight}</caption>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {values.map((value, index) => (
              <tr key={index}>
                <th scope="row">{index + 1}</th>
                <td>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </VisuallyHidden>
    </figure>
  )
}

export type SparklineProps = ChartBaseProps & {
  values: number[]
}

const SPARK_H = 40
const SPARK_MIN_STEP = 8

export function Sparkline({ insight, values, ariaSummary }: SparklineProps) {
  if (values.length === 0) {
    return <ChartEmptyState insight={insight} message="No data yet." />
  }
  if (values.length === 1) {
    // Refuses to draw a trend line from one point — a line needs two. Show the value
    // honestly instead of fabricating a slope.
    return <MiniBar insight={insight} values={values} ariaSummary={ariaSummary} />
  }

  const width = slopeTargetWidth(values, SPARK_H, SPARK_MIN_STEP)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const yScale = linearScale([min, max], [SPARK_H - 2, 2])
  const xScale = linearScale([0, values.length - 1], [0, width])

  const points = values.map((value, index) => `${xScale(index)},${yScale(value)}`).join(' ')
  const last = values[values.length - 1]

  const summary =
    ariaSummary ??
    `${insight}. Trend from ${values[0]} to ${last} over ${values.length} points, range ${min}–${max}.`

  return (
    <figure className="k-chart" role="img" aria-label={summary}>
      <figcaption className="k-chart__insight">{insight}</figcaption>
      <svg
        className="k-chart__viz k-chart__viz--fixed"
        viewBox={`0 0 ${width} ${SPARK_H}`}
        width={width}
        height={SPARK_H}
        aria-hidden="true"
      >
        <polyline className="k-chart__axis" fill="none" points={points} />
        <circle className="k-chart__dot" cx={xScale(values.length - 1)} cy={yScale(last)} r={2.5} />
      </svg>
      <VisuallyHidden>
        <table>
          <caption>{insight}</caption>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {values.map((value, index) => (
              <tr key={index}>
                <th scope="row">{index + 1}</th>
                <td>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </VisuallyHidden>
    </figure>
  )
}
