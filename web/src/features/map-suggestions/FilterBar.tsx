/**
 * Filter chips for type/status/family — shared with the map through `suggestionStore`
 * (`design.md` > "List/table specifics": "shared with the map through the same store").
 */

import type { CSSProperties } from 'react'
import { useFamilies } from '../families/useFamilies'
import { familyColor } from '../../design/familyColor'
import { hasActiveFilters, suggestionStore, useSuggestionView } from './store'
import type { SuggestionStatus, SuggestionType } from '../../app/types'
import './suggestionsList.css'

const TYPE_LABEL: Record<SuggestionType, string> = {
  region: 'Region',
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
}

const STATUS_LABEL: Record<SuggestionStatus, string> = {
  proposed: 'Proposed',
  shortlisted: 'Shortlisted',
  approved: 'Approved',
  scheduled: 'Scheduled',
  rejected: 'Rejected',
}

const TYPES: SuggestionType[] = ['region', 'accommodation', 'activity', 'meal']
const STATUSES: SuggestionStatus[] = ['proposed', 'shortlisted', 'approved', 'scheduled', 'rejected']

export function FilterBar() {
  const view = useSuggestionView()
  const { families } = useFamilies()

  return (
    <div className="sugg-filters" role="group" aria-label="Filters">
      <div className="sugg-filters__group" role="group" aria-label="Filter by type">
        {TYPES.map((type) => (
          <button
            key={type}
            type="button"
            className={`sugg-chip${view.filters.types.includes(type) ? ' is-on' : ''}`}
            aria-pressed={view.filters.types.includes(type)}
            onClick={() => suggestionStore.toggleType(type)}
          >
            {TYPE_LABEL[type]}
          </button>
        ))}
      </div>
      <div className="sugg-filters__group" role="group" aria-label="Filter by status">
        {STATUSES.map((status) => (
          <button
            key={status}
            type="button"
            className={`sugg-chip${view.filters.statuses.includes(status) ? ' is-on' : ''}`}
            aria-pressed={view.filters.statuses.includes(status)}
            onClick={() => suggestionStore.toggleStatus(status)}
          >
            {STATUS_LABEL[status]}
          </button>
        ))}
      </div>
      {families.length > 0 ? (
        <div className="sugg-filters__group" role="group" aria-label="Filter by family">
          {families.map((family) => (
            <button
              key={family.id}
              type="button"
              className={`sugg-chip${view.filters.familyIds.includes(family.id) ? ' is-on' : ''}`}
              aria-pressed={view.filters.familyIds.includes(family.id)}
              onClick={() => suggestionStore.toggleFamily(family.id)}
              style={{ '--sugg-chip-accent': familyColor(family) ?? undefined } as CSSProperties}
            >
              <span className="sugg-chip__dot" aria-hidden="true" />
              {family.name}
            </button>
          ))}
        </div>
      ) : null}
      {hasActiveFilters(view.filters) ? (
        <button type="button" className="sugg-filters__clear" onClick={() => suggestionStore.clearFilters()}>
          Clear filters
        </button>
      ) : null}
    </div>
  )
}
