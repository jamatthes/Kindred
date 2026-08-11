/**
 * DistributionStrip — thumbs voting as a single stacked strip: up / down / not voted.
 *
 * Each segment carries an icon *and* a count label in the legend below the strip — colour
 * is never the sole carrier of meaning (accessibility baseline, `plan/design-system.md`).
 */

import type { ChartBaseProps } from './types'
import { ChartEmptyState, VisuallyHidden } from './a11y'
import './charts.css'

export type DistributionStripProps = ChartBaseProps & {
  up: number
  down: number
  none: number
}

const WIDTH = 340
const HEIGHT = 26

function ThumbUpIcon() {
  return (
    <svg
      className="k-chart__legend-icon k-chart__legend-icon--up"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3Zm0 0 4.5-8a2 2 0 0 1 3.5 1.3V9h4a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 18 20H9a2 2 0 0 1-2-2v-7Z" />
    </svg>
  )
}

function ThumbDownIcon() {
  return (
    <svg
      className="k-chart__legend-icon k-chart__legend-icon--down"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path d="M17 13V4h3a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-3Zm0 0-4.5 8a2 2 0 0 1-3.5-1.3V15h-4a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6 4h9a2 2 0 0 1 2 2v7Z" />
    </svg>
  )
}

function NoneIcon() {
  return (
    <svg
      className="k-chart__legend-icon k-chart__legend-icon--none"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path d="M5 12h14" />
    </svg>
  )
}

export function DistributionStrip({ insight, up, down, none, ariaSummary }: DistributionStripProps) {
  const total = up + down + none
  if (total === 0) {
    return <ChartEmptyState insight={insight} message="No votes yet." />
  }

  const upW = (up / total) * WIDTH
  const downW = (down / total) * WIDTH
  const noneW = Math.max(0, WIDTH - upW - downW)

  const summary =
    ariaSummary ?? `${insight}. ${up} thumbs up, ${down} thumbs down, ${none} not voted, out of ${total}.`

  return (
    <figure className="k-chart" role="img" aria-label={summary}>
      <figcaption className="k-chart__insight">{insight}</figcaption>
      <svg className="k-chart__viz" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true">
        {up > 0 ? <rect x={0} y={0} width={upW} height={HEIGHT} rx={4} className="k-chart__seg--up" /> : null}
        {down > 0 ? (
          <rect x={upW} y={0} width={downW} height={HEIGHT} rx={4} className="k-chart__seg--down" />
        ) : null}
        {none > 0 ? (
          <rect x={upW + downW} y={0} width={noneW} height={HEIGHT} rx={4} className="k-chart__seg--none" />
        ) : null}
      </svg>
      <ul className="k-chart__legend">
        <li>
          <ThumbUpIcon /> Up <span className="k-chart__legend-count">{up}</span>
        </li>
        <li>
          <ThumbDownIcon /> Down <span className="k-chart__legend-count">{down}</span>
        </li>
        <li>
          <NoneIcon /> Not voted <span className="k-chart__legend-count">{none}</span>
        </li>
      </ul>
      <VisuallyHidden>
        <table>
          <caption>{insight}</caption>
          <thead>
            <tr>
              <th scope="col">Response</th>
              <th scope="col">Count</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Up</th>
              <td>{up}</td>
            </tr>
            <tr>
              <th scope="row">Down</th>
              <td>{down}</td>
            </tr>
            <tr>
              <th scope="row">Not voted</th>
              <td>{none}</td>
            </tr>
          </tbody>
        </table>
      </VisuallyHidden>
    </figure>
  )
}
