/**
 * The shared data-table pattern from `plan/design-system.md`: tri-state sort
 * (asc → desc → original), sticky header and sticky first column, tabular right-aligned
 * numerics, full-row click targets, density from spacing tokens.
 *
 * It lives in `app/ui` rather than in the admin console because it is the pattern for every
 * table in the product — the poll matrix, the suggestion list, the member overview — and the
 * third implementation of "click a header to sort" is the one that starts behaving
 * differently from the other two.
 *
 * **Tri-state matters.** Two-state sorting hides the original order for good, and in this
 * product the original order is usually meaningful (families by name, members as the server
 * ranked them). A third click gives it back rather than making the user reload.
 */

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import './DataTable.css'

export type Column<Row> = {
  key: string
  header: ReactNode
  /** Cell contents. */
  render: (row: Row) => ReactNode
  /** Return a comparable value to make the column sortable. Omit for an unsortable column. */
  sortBy?: (row: Row) => string | number | null
  /** Right-aligned and tabular — for numbers, dates and anything else compared by column. */
  numeric?: boolean
}

export type DataTableProps<Row> = {
  caption: string
  columns: Column<Row>[]
  rows: Row[]
  rowKey: (row: Row) => string
  onRowClick?: (row: Row) => void
  /** Rendered instead of the body when there are no rows — never a blank rectangle. */
  empty?: ReactNode
}

type SortState = { key: string; direction: 'asc' | 'desc' } | null

function compare(a: string | number | null, b: string | number | null): number {
  // Nulls sort last in ascending order whichever way the column runs: "never logged in" is
  // an absence, and burying it under real values makes the real values easier to scan.
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { sensitivity: 'base' })
}

export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
}: DataTableProps<Row>) {
  const [sort, setSort] = useState<SortState>(null)

  const sorted = useMemo(() => {
    if (sort === null) return rows
    const column = columns.find((c) => c.key === sort.key)
    if (!column?.sortBy) return rows
    const factor = sort.direction === 'asc' ? 1 : -1
    // A copy: sorting the caller's array in place would reorder their state behind them.
    return [...rows].sort((a, b) => factor * compare(column.sortBy!(a), column.sortBy!(b)))
  }, [rows, sort, columns])

  function toggle(key: string) {
    setSort((current) => {
      if (current?.key !== key) return { key, direction: 'asc' }
      if (current.direction === 'asc') return { key, direction: 'desc' }
      return null // third click: back to the order the server sent
    })
  }

  return (
    <div className="dt">
      <table className="dt__table">
        <caption className="dt__caption">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column, index) => {
              const active = sort?.key === column.key
              const ariaSort = active
                ? sort.direction === 'asc'
                  ? 'ascending'
                  : 'descending'
                : 'none'
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={column.sortBy ? ariaSort : undefined}
                  className={[
                    index === 0 ? 'dt__sticky-col' : '',
                    column.numeric ? 'dt__numeric' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  {column.sortBy ? (
                    <button
                      type="button"
                      className="dt__sort"
                      onClick={() => toggle(column.key)}
                    >
                      {column.header}
                      {/* An arrow *and* aria-sort: the icon is not the only carrier. */}
                      <span aria-hidden="true" className="dt__arrow">
                        {active ? (sort.direction === 'asc' ? '↑' : '↓') : '↕'}
                      </span>
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td className="dt__empty" colSpan={columns.length}>
                {empty ?? 'Nothing here yet.'}
              </td>
            </tr>
          ) : (
            sorted.map((row) => (
              <tr
                key={rowKey(row)}
                className={onRowClick ? 'dt__row dt__row--clickable' : 'dt__row'}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((column, index) => (
                  <td
                    key={column.key}
                    className={[
                      index === 0 ? 'dt__sticky-col' : '',
                      column.numeric ? 'dt__numeric' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
