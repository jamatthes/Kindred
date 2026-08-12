/**
 * The shared filter + selection state — "one store, two renderers" per `design.md` >
 * "Layout": the map and the list must never carry two copies of "what is selected" or
 * "which filters apply", or they will eventually disagree.
 *
 * A plain module-level store rather than a dependency: `app/router.ts` sets the precedent
 * for this codebase — `subscribe`/`notify` plus a `useSyncExternalStore` hook — and the
 * problem here (one small object, no middleware, no derived-state graph) does not need
 * more than that either.
 */

import { useSyncExternalStore } from 'react'
import type { SuggestionSortDir, SuggestionSortField, SuggestionStatus, SuggestionType } from '../../app/types'

export type SuggestionFilters = {
  types: SuggestionType[]
  statuses: SuggestionStatus[]
  familyIds: string[]
  /** "What needs my vote" (`voting-comments/design.md` V5/Phase 10) — a filter chip like
   * any other, so the map and list narrow to exactly the same set the count in the trip
   * chrome promises. Unlike the others it is client-side only (no server list param for
   * it; the consumer intersects `GET /me/pending-votes`' id list with the fetched page). */
  needsMyVote: boolean
}

export type SuggestionSort = { field: SuggestionSortField; dir: SuggestionSortDir } | null

export type SuggestionViewState = {
  filters: SuggestionFilters
  /** Selecting a suggestion is the one shared piece of state a pin click and a row click
   * both write — `design.md` S2: "Selection is a single shared piece of state." */
  selectedId: string | null
  sort: SuggestionSort
  /** Desktop: which the side panel shows when nothing is selected is always the list, so
   * this only matters once something *is* selected — the "List" toggle in `design.md`.
   * Mobile: which bottom sheet is raised. */
  panelView: 'list' | 'details'
}

const EMPTY_FILTERS: SuggestionFilters = { types: [], statuses: [], familyIds: [], needsMyVote: false }

let state: SuggestionViewState = {
  filters: EMPTY_FILTERS,
  selectedId: null,
  sort: null,
  panelView: 'list',
}

const listeners = new Set<() => void>()

function notify() {
  for (const listener of listeners) listener()
}

function setState(patch: Partial<SuggestionViewState>) {
  state = { ...state, ...patch }
  notify()
}

function toggleInList<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

export const suggestionStore = {
  getState: () => state,

  subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },

  select(id: string | null) {
    setState({ selectedId: id, panelView: id ? 'details' : 'list' })
  },

  showList() {
    setState({ panelView: 'list' })
  },

  toggleType(type: SuggestionType) {
    setState({ filters: { ...state.filters, types: toggleInList(state.filters.types, type) } })
  },

  toggleStatus(status: SuggestionStatus) {
    setState({ filters: { ...state.filters, statuses: toggleInList(state.filters.statuses, status) } })
  },

  toggleFamily(familyId: string) {
    setState({ filters: { ...state.filters, familyIds: toggleInList(state.filters.familyIds, familyId) } })
  },

  toggleNeedsMyVote() {
    setState({ filters: { ...state.filters, needsMyVote: !state.filters.needsMyVote } })
  },

  clearFilters() {
    setState({ filters: EMPTY_FILTERS })
  },

  /** Tri-state: asc → desc → original (`null`), matching `DataTable`'s cycle
   * (`app/ui/DataTable.tsx`) so the list's own header click and this shared sort agree. */
  cycleSort(field: SuggestionSortField) {
    setState({
      sort:
        state.sort?.field !== field
          ? { field, dir: 'asc' }
          : state.sort.dir === 'asc'
            ? { field, dir: 'desc' }
            : null,
    })
  },

  /** Test-only: resets the module singleton between test cases. */
  reset() {
    state = { filters: EMPTY_FILTERS, selectedId: null, sort: null, panelView: 'list' }
    notify()
  },
}

export function useSuggestionView(): SuggestionViewState {
  return useSyncExternalStore(suggestionStore.subscribe, suggestionStore.getState)
}

export function hasActiveFilters(filters: SuggestionFilters): boolean {
  return (
    filters.types.length > 0 ||
    filters.statuses.length > 0 ||
    filters.familyIds.length > 0 ||
    filters.needsMyVote
  )
}
