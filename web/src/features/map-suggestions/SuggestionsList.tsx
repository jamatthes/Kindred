/**
 * The list view — the same dataset as the map, per `design.md` S2. Built on `DataTable`
 * (`app/ui/DataTable.tsx`), which already implements the tri-state sort, sticky header,
 * tabular numerics, and full-row click targets `design.md` asks for, so this file is only
 * the suggestion-specific column definitions.
 */

import { useMemo } from 'react'
import { DataTable } from '../../app/ui/DataTable'
import type { Column } from '../../app/ui/DataTable'
import { Button } from '../../app/ui/primitives'
import type { Suggestion } from '../../app/types'
import { hasActiveFilters, suggestionStore, useSuggestionView } from './store'
import { familyColor } from '../../design/familyColor'
import './suggestionsList.css'

const TYPE_LABEL: Record<Suggestion['type'], string> = {
  region: 'Region',
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
}

const STATUS_LABEL: Record<Suggestion['status'], string> = {
  proposed: 'Proposed',
  shortlisted: 'Shortlisted',
  approved: 'Approved',
  scheduled: 'Scheduled',
  rejected: 'Rejected',
}

function primaryDistanceM(s: Suggestion): number | null {
  const withValue = s.distances.filter((d) => d.distance_m !== null)
  if (withValue.length === 0) return null
  return Math.min(...withValue.map((d) => d.distance_m as number))
}

function formatDistance(s: Suggestion): string {
  const m = primaryDistanceM(s)
  if (m === null) return '—'
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`
}

export type SuggestionsListProps = {
  suggestions: Suggestion[]
  onCreate?: () => void
  emptyAction?: boolean
}

export function SuggestionsList({ suggestions, onCreate, emptyAction = true }: SuggestionsListProps) {
  const view = useSuggestionView()

  const columns = useMemo<Column<Suggestion>[]>(
    () => [
      {
        key: 'title',
        header: 'Suggestion',
        render: (row) => (
          <span className="sugg-list__title">
            <span
              className="sugg-list__swatch"
              aria-hidden="true"
              style={{ background: familyColor({ color: row.created_by.family_color, color_custom: row.created_by.family_color_custom ?? null }) ?? 'var(--color-border-strong)' }}
            />
            {row.title}
            {row.children.length > 0 ? (
              <span className="sugg-list__count">{row.children.length} things here</span>
            ) : null}
          </span>
        ),
        sortBy: (row) => row.title,
      },
      {
        key: 'category',
        header: 'Type',
        render: (row) => TYPE_LABEL[row.type],
        sortBy: (row) => row.type,
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => <span className={`sugg-status sugg-status--${row.status}`}>{STATUS_LABEL[row.status]}</span>,
      },
      {
        key: 'votes',
        header: 'Votes',
        numeric: true,
        render: (row) =>
          row.vote_summary
            ? row.vote_summary.mode === 'score'
              ? (row.vote_summary.average?.toFixed(1) ?? '—')
              : `${row.vote_summary.up ?? 0}↑ ${row.vote_summary.down ?? 0}↓`
            : '—',
        sortBy: (row) => row.vote_summary?.average ?? (row.vote_summary?.up ?? null),
      },
      {
        key: 'comments',
        header: 'Comments',
        numeric: true,
        render: (row) => row.comment_count,
        sortBy: (row) => row.comment_count,
      },
      {
        key: 'distance',
        header: 'Distance',
        numeric: true,
        render: formatDistance,
        sortBy: primaryDistanceM,
      },
    ],
    [],
  )

  if (suggestions.length === 0) {
    return (
      <div className="sugg-empty">
        {hasActiveFilters(view.filters) ? (
          <>
            <p>No suggestions match these filters.</p>
            <Button variant="secondary" onClick={() => suggestionStore.clearFilters()}>
              Clear filters
            </Button>
          </>
        ) : (
          <>
            <p>No suggestions yet — drop the first pin.</p>
            {emptyAction && onCreate ? <Button onClick={onCreate}>Suggest a place</Button> : null}
          </>
        )}
      </div>
    )
  }

  return (
    <DataTable
      caption="Trip suggestions"
      columns={columns}
      rows={suggestions}
      rowKey={(row) => row.id}
      onRowClick={(row) => suggestionStore.select(row.id)}
    />
  )
}
