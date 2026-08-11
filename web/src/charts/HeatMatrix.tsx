/**
 * HeatMatrix — members × options score matrix, the spreadsheet this replaces.
 *
 * Unlike the rest of `web/src/charts/`, this is a real `<table>`, not SVG — a score
 * matrix *is* tabular data, and genuine sticky row/column headers during scroll
 * (`plan/features/design-system/design.md`: "matching the Table primitive's behaviour")
 * only exist natively on a table with CSS `position: sticky`. See `HeatMatrix.css`.
 *
 * Each cell is tinted from the shared `--scale-pref-N` ramp and **always prints the
 * number** on top ("consumers must render the number"). A member who hasn't voted on an
 * option renders a hatched cell with an explicit "—" — never a zero, which would
 * silently count as the worst possible score.
 */

import type { ChartBaseProps, ChartMember, ChartOption } from './types'
import { ChartEmptyState } from './a11y'
import { prefRampStep } from './scales'
import './charts.css'
import './HeatMatrix.css'

export type HeatMatrixProps = ChartBaseProps & {
  rows: ChartMember[]
  cols: ChartOption[]
  /** `values[rowIndex][colIndex]`. `null` = hasn't voted — rendered hatched, never as 0. */
  values: (number | null)[][]
}

function cellAt(values: (number | null)[][], row: number, col: number): number | null {
  return values[row]?.[col] ?? null
}

export function HeatMatrix({ insight, rows, cols, values, ariaSummary }: HeatMatrixProps) {
  if (rows.length === 0 || cols.length === 0) {
    return <ChartEmptyState insight={insight} message="No votes yet." />
  }

  const summary =
    ariaSummary ??
    `Score matrix, ${rows.length} member${rows.length === 1 ? '' : 's'} across ${cols.length} option${cols.length === 1 ? '' : 's'}.`

  return (
    <figure className="k-chart">
      <figcaption className="k-chart__insight">{insight}</figcaption>
      <div className="k-heat" data-testid="heat-scroll">
        <table className="k-heat-table">
          <caption className="k-chart-visually-hidden">{summary}</caption>
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
                  if (raw === null) {
                    return (
                      <td
                        key={col.id}
                        data-testid="heat-cell-empty"
                        className="k-heat-cell--empty"
                        aria-label={`${row.label}, ${col.label}: not voted`}
                      >
                        —
                      </td>
                    )
                  }
                  const step = prefRampStep(raw)
                  return (
                    <td
                      key={col.id}
                      data-testid="heat-cell"
                      className={`k-heat-cell--${step}`}
                      aria-label={`${row.label}, ${col.label}: ${step}`}
                    >
                      {step}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}
