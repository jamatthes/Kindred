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
import { CompactVoteTally } from '../voting-comments/VoteTally'
import { useFamilies } from '../families/useFamilies'
import { DistanceCell } from '../distances/DistanceCell'
import { DistancePerspectiveSelector } from '../distances/DistancePerspectiveSelector'
import { useBulkDistances } from '../distances/useBulkDistances'
import { distanceForFamily, distanceSortValue } from '../distances/distanceOrder'
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

export type SuggestionsListProps = {
  suggestions: Suggestion[]
  /** Needed only to refetch another family's perspective (`useBulkDistances`); the default
   * own-family view needs neither, which is why both are optional rather than plumbed
   * through every existing call site and test. */
  tripId?: string
  ownFamilyId?: string | null
  onCreate?: () => void
  emptyAction?: boolean
}

export function SuggestionsList({
  suggestions,
  tripId = undefined,
  ownFamilyId = null,
  onCreate,
  emptyAction = true,
}: SuggestionsListProps) {
  const view = useSuggestionView()
  const { families } = useFamilies()
  const perspectiveId = view.distancePerspectiveFamilyId
  // Own perspective needs no extra request — every suggestion already carries its own
  // family's row first (`design.md`'s own reasoning for the bulk endpoint existing at all).
  const { bySuggestion } = useBulkDistances(tripId ?? null, perspectiveId)

  const perspectiveName =
    perspectiveId === null
      ? 'you'
      : (families.find((f) => f.id === perspectiveId)?.name ?? 'that family')

  function distanceFor(row: Suggestion) {
    if (perspectiveId === null) return distanceForFamily(row.distances, ownFamilyId)
    const rows = bySuggestion[row.id] ?? row.distances
    return distanceForFamily(rows, perspectiveId)
  }

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
        render: (row) => <CompactVoteTally summary={row.vote_summary} />,
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
        header: `Distance (from ${perspectiveName})`,
        numeric: true,
        render: (row) => <DistanceCell distance={distanceFor(row)} />,
        sortBy: (row) => distanceSortValue(distanceFor(row)),
      },
    ],
    // `distanceFor` itself is deliberately not a dep: it is a plain closure recreated every
    // render, and listing it would make this memo useless (a "stable" dep that never is).
    // Its own inputs are, so recomputing exactly when they change is what this list gives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [perspectiveId, bySuggestion, ownFamilyId, perspectiveName],
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
    <>
      <DistancePerspectiveSelector ownFamilyId={ownFamilyId} />
      <DataTable
        caption="Trip suggestions"
        columns={columns}
        rows={suggestions}
        rowKey={(row) => row.id}
        onRowClick={(row) => suggestionStore.select(row.id)}
      />
    </>
  )
}
