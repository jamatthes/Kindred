/**
 * HeatMatrix — members × options score matrix, the spreadsheet this replaces.
 *
 * Each cell is tinted from the shared `--scale-pref-N` ramp and **always prints the
 * number** on top (`plan/features/design-system/design.md`: "consumers must render the
 * number"). A member who hasn't voted on an option renders a hatched cell with an
 * explicit "—" — never a zero, which would silently count as the worst possible score.
 */

import type { ChartBaseProps, ChartMember, ChartOption } from './types'
import { ChartEmptyState, VisuallyHidden } from './a11y'
import { prefRampStep } from './scales'
import './charts.css'

export type HeatMatrixProps = ChartBaseProps & {
  rows: ChartMember[]
  cols: ChartOption[]
  /** `values[rowIndex][colIndex]`. `null` = hasn't voted — rendered hatched, never as 0. */
  values: (number | null)[][]
}

const CELL_W = 68
const CELL_H = 30
const LABEL_W = 78
const HEADER_H = 30
const GAP = 3
const HATCH_ID = 'k-heat-hatch'

function cellAt(values: (number | null)[][], row: number, col: number): number | null {
  return values[row]?.[col] ?? null
}

export function HeatMatrix({ insight, rows, cols, values, ariaSummary }: HeatMatrixProps) {
  if (rows.length === 0 || cols.length === 0) {
    return <ChartEmptyState insight={insight} message="No votes yet." />
  }

  const width = LABEL_W + cols.length * CELL_W
  const height = HEADER_H + rows.length * CELL_H

  const summary =
    ariaSummary ??
    `${insight}. Score matrix, ${rows.length} member${rows.length === 1 ? '' : 's'} across ${cols.length} option${cols.length === 1 ? '' : 's'}.`

  return (
    <figure className="k-chart" role="img" aria-label={summary}>
      <figcaption className="k-chart__insight">{insight}</figcaption>
      <div className="k-chart__scroll">
        <svg className="k-chart__viz" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
          <defs>
            <pattern
              id={HATCH_ID}
              width={6}
              height={6}
              patternTransform="rotate(45)"
              patternUnits="userSpaceOnUse"
            >
              <line x1={0} y1={0} x2={0} y2={6} className="k-chart__hatch-line" />
            </pattern>
          </defs>

          {cols.map((col, colIndex) => (
            <text
              key={col.id}
              className="k-chart__col-label"
              x={LABEL_W + colIndex * CELL_W + CELL_W / 2}
              y={HEADER_H - 10}
              textAnchor="middle"
            >
              {col.label}
            </text>
          ))}

          {rows.map((row, rowIndex) => (
            <g key={row.id}>
              <text
                className="k-chart__label"
                x={LABEL_W - GAP * 2}
                y={HEADER_H + rowIndex * CELL_H + CELL_H / 2 + 4}
                textAnchor="end"
              >
                {row.label}
              </text>
              {cols.map((col, colIndex) => {
                const raw = cellAt(values, rowIndex, colIndex)
                const x = LABEL_W + colIndex * CELL_W + GAP / 2
                const y = HEADER_H + rowIndex * CELL_H + GAP / 2
                const w = CELL_W - GAP
                const h = CELL_H - GAP
                const cx = x + w / 2
                const cy = y + h / 2 + 4

                if (raw === null) {
                  return (
                    <g key={col.id} data-testid="heat-cell-empty">
                      <rect x={x} y={y} width={w} height={h} rx={4} className="k-chart__cell k-chart__cell--empty" />
                      <rect x={x} y={y} width={w} height={h} rx={4} fill={`url(#${HATCH_ID})`} />
                      <text className="k-chart__cell-value k-chart__cell-value--muted" x={cx} y={cy} textAnchor="middle">
                        —
                      </text>
                    </g>
                  )
                }

                const step = prefRampStep(raw)
                return (
                  <g key={col.id} data-testid="heat-cell">
                    <rect
                      x={x}
                      y={y}
                      width={w}
                      height={h}
                      rx={4}
                      className={`k-chart__cell k-chart__cell--${step}`}
                    />
                    <text className="k-chart__cell-value" x={cx} y={cy} textAnchor="middle">
                      {step}
                    </text>
                  </g>
                )
              })}
            </g>
          ))}
        </svg>
      </div>
      <VisuallyHidden>
        <table>
          <caption>{insight}</caption>
          <thead>
            <tr>
              <th scope="col">Member</th>
              {cols.map((col) => (
                <th scope="col" key={col.id}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={row.id}>
                <th scope="row">{row.label}</th>
                {cols.map((col, colIndex) => {
                  const raw = cellAt(values, rowIndex, colIndex)
                  return <td key={col.id}>{raw === null ? 'not voted' : raw}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </VisuallyHidden>
    </figure>
  )
}
